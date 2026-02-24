from abc import ABC, abstractmethod
from .common import flatten_name, resolve_target_path, get_exit_sequence, get_entry_sequence, parse_fork_target, resolve_state_data, get_lca_index
import re
import sys


class BaseGenerator(ABC):
    """Abstract base class for HSM code generators.

    Subclasses must define the following class-level template attributes:
        FUNC_PREAMBLE, LEAF_TEMPLATE, COMPOSITE_OR_TEMPLATE,
        COMPOSITE_AND_TEMPLATE, INSPECTOR_TEMPLATE

    Subclasses must implement:
        assemble_output() — combine generated parts into final output
    """

    FUNC_PREAMBLE = None
    LEAF_TEMPLATE = None
    COMPOSITE_OR_TEMPLATE = None
    COMPOSITE_AND_TEMPLATE = None
    INSPECTOR_TEMPLATE = None

    def __init__(self, data):
        self.data = data
        self.state_counter = 0
        self.outputs = {'context_ptrs': [], 'context_init': [], 'functions': [], 'impls': []}
        self.inspect_list = []
        self.decisions = data.get('decisions', {})
        self.hooks = data.get('hooks', {})
        if 'transition' not in self.hooks and 'transition' in data:
             self.hooks['transition'] = data['transition']
        self.includes = data.get('includes', '')

    def _fmt_func(self, path):
        """Format an exit function name for the given state path."""
        return "state_" + flatten_name(path, "_") + "_exit"

    def _fmt_entry(self, path, suffix="_entry"):
        """Format an entry/start function name for the given state path."""
        return "state_" + flatten_name(path, "_") + suffix

    def generate(self):
        """Run the full generation pipeline: recurse, inspect, assemble."""
        root_data = {
            'initial': self.data['initial'],
            'states': self.data['states'],
            'history': False,
            'entry': self.data.get('entry', '// Root Entry'),
            'do': self.data.get('do', '// Root Do'),
            'exit': self.data.get('exit', '// Root Exit')
        }

        self.recurse(['root'], root_data, None)
        self.gen_inspector(['root'], root_data, 'root')
        return self.assemble_output()

    @abstractmethod
    def assemble_output(self):
        """Combine generated parts into final output string(s).

        Returns:
            tuple: (primary_source, secondary_source) — e.g. (rust_code, "")
                   or (c_source, header_source).
        """
        pass

    def emit_transition_logic(self, name_path, t, indent_level=1):
        indent = "    " * indent_level
        code = ""
        raw_target = t.get('to')

        test_val = t.get('guard', True)
        if test_val is True: test_cond = "true"
        elif test_val is False: test_cond = "false"
        else: test_cond = str(test_val)

        test_cond = re.sub(r'IN_STATE\(([\w_]+)\)', r'ctx.in_state_\1()', test_cond)

        code += f"{indent}if {test_cond} {{\n"

        src_str = "/" + "/".join(name_path[1:])
        dst_str = "???"
        is_termination = False

        is_decision = isinstance(raw_target, str) and raw_target.startswith('@')
        decision_name = raw_target[1:] if is_decision else None

        if raw_target is None or raw_target == "null" or raw_target == "":
            dst_str = "Termination"
            is_termination = True
        elif is_decision:
            dst_str = f"Decision({decision_name})"
        else:
            base_target, forks = parse_fork_target(raw_target)
            target_path = resolve_target_path(name_path, base_target)
            if forks:
                dst_str = "/" + "/".join(target_path[1:]) + str(forks)
            else:
                dst_str = "/" + "/".join(target_path[1:])

        hook_code = self.hooks.get('transition', '')
        if not is_decision:
             code += f'{indent}    let t_src = "{src_str}";\n'
             code += f'{indent}    let t_dst = "{dst_str}";\n'
             if hook_code:
                 formatted_hook = "\n".join([f"{indent}    {line}" for line in hook_code.splitlines()])
                 code += formatted_hook + "\n"

        code += f"{indent}    ctx.transition_fired = true;\n"

        action_code = t.get('action')
        if action_code:
             formatted_action = "\n".join([f"{indent}    {line}" for line in action_code.splitlines()])
             code += formatted_action + "\n"

        if is_termination:
            exit_funcs = get_exit_sequence(name_path, ['root'], self._fmt_func)
            code += "".join([f"{indent}    {fn}(ctx);\n" for fn in exit_funcs])
            code += f"{indent}    state_root_exit(ctx);\n"
            code += f"{indent}    ctx.terminated = true;\n"
            code += f"{indent}    return;\n"

        elif is_decision:
            decision_rules = self.decisions[decision_name]
            for rule in decision_rules:
                code += self.emit_transition_logic(name_path, rule, indent_level + 1)
        else:
            base_target, forks = parse_fork_target(raw_target)
            target_path = resolve_target_path(name_path, base_target)

            # LCA calculation
            lca_index = get_lca_index(name_path, target_path)

            # --- CROSS-LIMB ORTHOGONAL CHECK ---
            is_cross_limb = False
            container_path = name_path[:lca_index]
            lca_data = resolve_state_data(self.data, container_path)

            if lca_data and lca_data.get('orthogonal', False):
                limb_idx = lca_index

                if len(name_path) > limb_idx and len(target_path) > limb_idx:
                    source_limb = name_path[limb_idx]
                    target_limb = target_path[limb_idx]

                    if source_limb != target_limb:
                        is_cross_limb = True

                        target_limb_path = name_path[:lca_index] + [target_limb]
                        target_limb_c_name = flatten_name(target_limb_path, "_")

                        # --- OPTIMIZED HOT-SWAP ---
                        limb_data = resolve_state_data(self.data, target_limb_path)
                        is_composite_limb = limb_data and 'states' in limb_data
                        is_targeting_deeper = len(target_path) > len(target_limb_path)

                        if is_composite_limb and is_targeting_deeper:
                            code += f"{indent}    if let Some(exit_fn) = ctx.ptr_{target_limb_c_name}_exit {{ exit_fn(ctx); }}\n"
                            entry_source = target_limb_path
                        else:
                            code += f"{indent}    if let Some(exit_fn) = ctx.ptr_{target_limb_c_name}_region_exit {{ exit_fn(ctx); }}\n"
                            entry_source = container_path

                        # 3. Entry Sequence
                        if forks is None:
                             entry_funcs = get_entry_sequence(entry_source, target_path, self._fmt_entry)
                             code += "".join([f"{indent}    {fn}(ctx);\n" for fn in entry_funcs])
                        else:
                             def _fmt_entry_forced_start(path, suffix):
                                if path == target_path:
                                    return "state_" + flatten_name(path, "_") + "_start"
                                return "state_" + flatten_name(path, "_") + suffix
                             entry_funcs = get_entry_sequence(entry_source, target_path, _fmt_entry_forced_start)
                             code += "".join([f"{indent}    {fn}(ctx);\n" for fn in entry_funcs])

                        code += f"{indent}    return;\n"
                        code += f"{indent}}}\n"
                        return code

            # --- IMPLICIT ORTHOGONAL / LOCAL LIMB LOGIC ---
            if forks is None:
                parallel_ancestor_idx = -1
                for i in range(len(target_path)):
                    partial_path = target_path[:i+1]
                    s_data = resolve_state_data(self.data, partial_path)
                    if s_data and s_data.get('orthogonal', False):
                        parallel_ancestor_idx = i
                        break

                if parallel_ancestor_idx != -1 and parallel_ancestor_idx < len(target_path) - 1:
                    limb_idx = parallel_ancestor_idx + 1
                    is_same_limb = False
                    if len(name_path) > limb_idx:
                        if name_path[limb_idx] == target_path[limb_idx]:
                            is_same_limb = True

                    if not is_same_limb:
                        base_path_list = target_path[:parallel_ancestor_idx+1]
                        fork_parts = target_path[parallel_ancestor_idx+1:]
                        fork_str = "/".join(fork_parts)
                        target_path = base_path_list
                        forks = [fork_str]
                        base_target = "/" + "/".join(base_path_list[1:])

            # --- DYNAMIC CHILD EXIT FIX (For Container Transitions) ---
            if lca_index >= len(name_path):
                 my_data = resolve_state_data(self.data, name_path)
                 if my_data and 'states' in my_data and not my_data.get('orthogonal', False):
                      my_c_name = flatten_name(name_path, "_")
                      code += f"{indent}    if let Some(exit_fn) = ctx.ptr_{my_c_name}_exit {{ exit_fn(ctx); }}\n"

            # --- Standard Exit Sequence ---
            exit_funcs = get_exit_sequence(name_path, target_path, self._fmt_func)
            code += "".join([f"{indent}    {fn}(ctx);\n" for fn in exit_funcs])

            if forks is None:
                entry_funcs = get_entry_sequence(name_path, target_path, self._fmt_entry)
                code += "".join([f"{indent}    {fn}(ctx);\n" for fn in entry_funcs])
            else:
                def _fmt_entry_forced_start(path, suffix):
                    if path == target_path:
                        return "state_" + flatten_name(path, "_") + "_start"
                    return "state_" + flatten_name(path, "_") + suffix

                entry_funcs = get_entry_sequence(name_path, target_path, _fmt_entry_forced_start)
                code += "".join([f"{indent}    {fn}(ctx);\n" for fn in entry_funcs])

                parallel_data = resolve_state_data(self.data, target_path)
                if not parallel_data or 'states' not in parallel_data:
                     pass
                else:
                    for child_name, child_data in parallel_data['states'].items():
                        matching_fork = None
                        for fork in forks:
                            parts = fork.split('/')
                            if parts[0] == child_name:
                                matching_fork = fork
                                break

                        if matching_fork:
                            fork_target_path = target_path + matching_fork.split('/')
                            deep_entries = get_entry_sequence(target_path, fork_target_path, self._fmt_entry)
                            code += "".join([f"{indent}    {fn}(ctx);\n" for fn in deep_entries])
                        else:
                            child_path = target_path + [child_name]
                            init_func = self._fmt_entry(child_path, "_entry")
                            code += f"{indent}    {init_func}(ctx);\n"

            code += f"{indent}    return;\n"

        code += f"{indent}}}\n"
        return code

    def recurse(self, name_path, data, parent_ptrs):
        try:
            my_id_num = self.state_counter
            self.state_counter += 1
            my_c_name = flatten_name(name_path, "_")

            disp_name = "/" + "/".join(name_path[1:]) if len(name_path) > 1 else "/"
            preamble = self.FUNC_PREAMBLE.format(short_name=name_path[-1], display_name=disp_name, state_id=my_id_num)

            parent_run_ptr = parent_ptrs[0] if parent_ptrs else None
            parent_exit_ptr = parent_ptrs[1] if parent_ptrs else None
            parent_hist_ptr = parent_ptrs[2] if parent_ptrs else None

            if parent_run_ptr:
                method = f"""
        pub fn in_state_{my_c_name}(&self) -> bool {{
            self.{parent_run_ptr}.map(|f| f as usize) == Some(state_{my_c_name}_do as usize)
        }}"""
                self.outputs['impls'].append(method)

            set_parent_code = ""
            clear_parent_code = ""

            if parent_run_ptr:
                set_parent_code += f"ctx.{parent_run_ptr} = Some(state_{my_c_name}_do);\n    "
                set_parent_code += f"ctx.{parent_exit_ptr} = Some(state_{my_c_name}_exit);"

                if parent_hist_ptr:
                    set_parent_code += f"\n    ctx.{parent_hist_ptr} = Some(state_{my_c_name}_entry);"

                clear_parent_code += f"ctx.{parent_run_ptr} = None;\n    "
                clear_parent_code += f"ctx.{parent_exit_ptr} = None;"

            trans_code = ""
            for i, t in enumerate(data.get('transitions', [])):
                try:
                    trans_code += self.emit_transition_logic(name_path, t, 1)
                except Exception as e:
                    raise Exception(f"Transition #{i+1} logic error: {e}")

            is_composite = 'states' in data
            is_parallel = data.get('orthogonal', False)

            h_entry = self.hooks.get('entry', '')
            h_do = self.hooks.get('do', '')
            h_exit = self.hooks.get('exit', '')

            if is_composite:
                if is_parallel:
                    if parent_run_ptr:
                        safety_check = f"if !ctx.in_state_{my_c_name}() || ctx.transition_fired {{ return; }}"
                    else:
                        safety_check = f"if ctx.transition_fired {{ return; }}"

                    p_entries, p_exits, p_ticks = "", "", ""
                    for child_name, child_data in data['states'].items():
                        child_path = name_path + [child_name]
                        child_c_name = flatten_name(child_path, "_")

                        region_ptr = f"ptr_{child_c_name}_region"
                        region_exit_ptr = f"{region_ptr}_exit"

                        self.outputs['context_ptrs'].append(f"pub {region_ptr}: Option<StateFn>,")
                        self.outputs['context_ptrs'].append(f"pub {region_exit_ptr}: Option<StateFn>,")
                        self.outputs['context_init'].append(f"{region_ptr}: None,")
                        self.outputs['context_init'].append(f"{region_exit_ptr}: None,")

                        p_entries += f"    state_{child_c_name}_entry(ctx);\n"
                        p_exits += f"    if let Some(f) = ctx.{region_exit_ptr} {{ f(ctx); }}\n"
                        p_ticks += f"    state_{child_c_name}_do(ctx);\n"
                        if safety_check:
                            p_ticks += f"    {safety_check}\n"

                        self.recurse(child_path, child_data, (region_ptr, region_exit_ptr, None))

                    func_body = self.COMPOSITE_AND_TEMPLATE.format(
                        c_name=my_c_name, state_id=my_id_num, preamble=preamble,
                        hook_entry=h_entry, hook_do=h_do, hook_exit=h_exit,
                        entry=data.get('entry', ''), exit=data.get('exit', ''), do=data.get('do', ''),
                        transitions=trans_code,
                        set_parent=set_parent_code, clear_parent=clear_parent_code,
                        parallel_entries=p_entries, parallel_exits=p_exits, parallel_ticks=p_ticks,
                        safety_check=safety_check
                    )

                else:
                    my_ptr = f"ptr_{my_c_name}"
                    my_exit_ptr = f"{my_ptr}_exit"
                    my_hist = f"hist_{my_c_name}"

                    self.outputs['context_ptrs'].append(f"pub {my_ptr}: Option<StateFn>,")
                    self.outputs['context_ptrs'].append(f"pub {my_exit_ptr}: Option<StateFn>,")
                    self.outputs['context_ptrs'].append(f"pub {my_hist}: Option<StateFn>,")

                    self.outputs['context_init'].append(f"{my_ptr}: None,")
                    self.outputs['context_init'].append(f"{my_exit_ptr}: None,")
                    self.outputs['context_init'].append(f"{my_hist}: None,")

                    init_target = flatten_name(name_path + [data['initial']], "_")
                    hist_bool = "true" if data.get('history', False) else "false"

                    func_body = self.COMPOSITE_OR_TEMPLATE.format(
                        c_name=my_c_name, state_id=my_id_num, preamble=preamble,
                        hook_entry=h_entry, hook_do=h_do, hook_exit=h_exit,
                        entry=data.get('entry', ''), exit=data.get('exit', ''), do=data.get('do', ''),
                        transitions=trans_code, history=hist_bool,
                        self_ptr=my_ptr, self_exit_ptr=my_exit_ptr, self_hist_ptr=my_hist,
                        initial_target=init_target,
                        set_parent=set_parent_code, clear_parent=clear_parent_code
                    )

                    use_history = data.get('history', False)
                    child_hist_ptr = my_hist if use_history else None

                    for child_name, child_data in data['states'].items():
                        self.recurse(name_path + [child_name], child_data, (my_ptr, my_exit_ptr, child_hist_ptr))
            else:
                func_body = self.LEAF_TEMPLATE.format(
                    c_name=my_c_name, state_id=my_id_num, preamble=preamble,
                    hook_entry=h_entry, hook_do=h_do, hook_exit=h_exit,
                    entry=data.get('entry', ''), exit=data.get('exit', ''), do=data.get('do', ''),
                    transitions=trans_code,
                    set_parent=set_parent_code, clear_parent=clear_parent_code
                )

            self.outputs['functions'].append(func_body)

        except Exception as e:
            raise Exception(f"Error generating state '{'/'.join(name_path)}': {str(e)}")

    def gen_inspector(self, name_path, data, ptr_name_struct):
        my_c_name = flatten_name(name_path, "_")
        disp_name = "" if name_path == ['root'] else name_path[-1]
        push_name = f'buf.push_str("{disp_name}");' if disp_name else ""
        content = ""

        is_composite = 'states' in data
        if is_composite:
            if data.get('orthogonal', False):
                content += 'buf.push_str("/[");\n'
                children = list(data['states'].items())
                for i, (child_name, child_data) in enumerate(children):
                    child_path = name_path + [child_name]
                    child_func = f"inspect_{flatten_name(child_path, '_')}"
                    self.gen_inspector(child_path, child_data, None)
                    content += f"    {child_func}(ctx, buf);\n"
                    if i < len(children)-1: content += '    buf.push_str(",");\n'
                content += 'buf.push_str("]");\n'
            else:
                my_ptr = f"ptr_{my_c_name}"
                for child_name, child_data in data['states'].items():
                    self.gen_inspector(name_path + [child_name], child_data, my_ptr)
                first = True
                for child_name, child_data in data['states'].items():
                    c_name = flatten_name(name_path + [child_name], "_")
                    else_txt = "else " if not first else ""
                    content += f"    {else_txt}if ctx.{my_ptr}.map(|f| f as usize) == Some(state_{c_name}_do as usize) {{\n"
                    content += f'        buf.push_str("/");\n'
                    content += f"        inspect_{c_name}(ctx, buf);\n"
                    content += "    }\n"
                    first = False

        self.inspect_list.append(self.INSPECTOR_TEMPLATE.format(c_name=my_c_name, push_name=push_name, content=content))
