from .common import flatten_name, resolve_target_path, get_exit_sequence

HEADER = """
#ifndef STATEMACHINE_H
#define STATEMACHINE_H
#include <stdio.h>
#include <stdbool.h>
#include <string.h>

#define TOTAL_STATES %d

typedef struct SM_Context SM_Context;
typedef void (*StateFunc)(SM_Context* ctx);

// --- Forward Declarations ---
%s

struct SM_Context {
    void* owner;
    double now; 
    double state_timers[TOTAL_STATES];

    // User Context Variables
    %s
    
    // Hierarchy Pointers
    %s
};

typedef struct {
    SM_Context ctx;
    StateFunc root;
} StateMachine;

void sm_init(StateMachine* sm);
void sm_tick(StateMachine* sm);
void sm_get_state_str(StateMachine* sm, char* buffer, size_t max_len);

// --- Macros ---
#define IN_STATE(statename) IN_STATE_##statename
%s

#endif
"""

SOURCE_TOP = """
#include "statemachine.h"

// --- User Includes ---
%s

// --- Helpers ---
static void safe_strcat(char* dest, const char* src, size_t* offset, size_t max) {
    size_t len = strlen(src);
    if (*offset + len >= max) return;
    strcpy(dest + *offset, src);
    *offset += len;
}

// --- State Logic ---
"""

FUNC_PREAMBLE = """
    (void)ctx;
    const char* state_name = "{short_name}";
    const char* state_full_name = "{display_name}";
    (void)state_name; (void)state_full_name;
    double time = ctx->now - ctx->state_timers[{state_id}];
    (void)time; 
"""

LEAF_TEMPLATE = """
void state_{c_name}_start(SM_Context* ctx) {{
    ctx->state_timers[{state_id}] = ctx->now;
    {preamble}
    {hook_entry}
    ctx->{parent_ptr} = state_{c_name}_run;
}}

void state_{c_name}_entry(SM_Context* ctx) {{
    state_{c_name}_start(ctx);
}}
...
"""

COMPOSITE_OR_TEMPLATE = """
void state_{c_name}_start(SM_Context* ctx) {{
    ctx->state_timers[{state_id}] = ctx->now;
    {preamble}
    {hook_entry}
    {set_parent}
}}

void state_{c_name}_entry(SM_Context* ctx) {{
    state_{c_name}_start(ctx);
    if (({history}) && ctx->{self_hist_ptr} != NULL) {{
        ctx->{self_hist_ptr}(ctx);
    }} else {{
        state_{initial_target}_entry(ctx);
    }}
}}
...
"""

COMPOSITE_AND_TEMPLATE = """
void state_{c_name}_start(SM_Context* ctx) {{
    ctx->state_timers[{state_id}] = ctx->now;
    {preamble}
    {hook_entry}
    {history_save}
    {set_parent}
}}

void state_{c_name}_entry(SM_Context* ctx) {{
    state_{c_name}_start(ctx);
    // Parallel Entry: Start all regions
    {parallel_entries}
}}

void state_{c_name}_exit(SM_Context* ctx) {{
    {preamble}
    {hook_exit}
    // Parallel Exit: Force exit all active regions
    {parallel_exits}
    {exit}
}}

void state_{c_name}_run(SM_Context* ctx) {{
    {preamble}
    {hook_run}
    {run}
    // Parallel Run: Tick all regions
    {parallel_ticks}
    {transitions}
}}
"""

class CGenerator:
    def __init__(self, data):
        self.data = data
        self.state_counter = 0
        self.outputs = {'context_ptrs': [], 'functions': [], 'forwards': [], 'macros': []}
        self.inspect_list = []
        self.decisions = data.get('decisions', {})
        self.hooks = data.get('hooks', {})
        self.includes = data.get('includes', '')

    def generate(self):
        root_data = {
            'initial': self.data['initial'], 'states': self.data['states'],
            'history': False, 'entry': "// Root Entry", 'run': "// Root Run", 'exit': "// Root Exit"
        }
        
        self.recurse(['root'], root_data, None)
        self.gen_inspector(['root'], root_data, 'root')

        header = HEADER % (
            self.state_counter,
            "\n".join(self.outputs['forwards']),
            self.data.get('context', ''),
            "\n    ".join(self.outputs['context_ptrs']),
            "\n".join(self.outputs['macros'])
        )

        source = SOURCE_TOP % (self.includes) + "\n".join(self.outputs['functions'])
        source += "\n// --- Inspection ---\n" + "\n".join(self.inspect_list)
        
        source += """
void sm_init(StateMachine* sm) {
    memset(&sm->ctx, 0, sizeof(sm->ctx));
    sm->ctx.owner = sm;
    state_root_entry(&sm->ctx); 
    sm->root = state_root_run; 
}
void sm_tick(StateMachine* sm) {
    if (sm->root) sm->root(&sm->ctx);
}
void sm_get_state_str(StateMachine* sm, char* buffer, size_t max_len) {
    size_t offset = 0;
    buffer[0] = '\\0';
    if (sm->root) inspect_root(&sm->ctx, buffer, &offset, max_len);
}
"""
        return header, source

    def emit_transition_logic(self, name_path, t, indent_level=1):
        indent = "    " * indent_level
        code = ""
        target_str = t['transfer_to']
        
        test_val = t.get('test', True)
        if test_val is True: test_cond = "true"
        elif test_val is False: test_cond = "false"
        else: test_cond = str(test_val)
        
        code += f"{indent}if ({test_cond}) {{\n"

        if target_str in self.decisions:
            decision_rules = self.decisions[target_str]
            for rule in decision_rules:
                code += self.emit_transition_logic(name_path, rule, indent_level + 1)
        else:
            target_path = resolve_target_path(name_path, target_str)
            
            exit_funcs = get_exit_sequence(name_path, target_path, lambda p: "state_" + flatten_name(p, "_") + "_exit")
            
            from .common import get_entry_sequence
            entry_funcs = get_entry_sequence(name_path, target_path, lambda p, s: "state_" + flatten_name(p, "_") + s)
            
            exit_calls = "".join([f"{indent}    {fn}(ctx);\n" for fn in exit_funcs])
            entry_calls = "".join([f"{indent}    {fn}(ctx);\n" for fn in entry_funcs])
            
            code += f"{exit_calls}"
            code += f"{entry_calls}"
            code += f"{indent}    return;\n"

        code += f"{indent}}}\n"
        return code

    def recurse(self, name_path, data, parent_ptrs):
        my_id_num = self.state_counter
        self.state_counter += 1
        my_c_name = flatten_name(name_path, "_")
        
        disp_name = "/" + "/".join(name_path[1:]) if len(name_path) > 1 else "/"
        preamble = FUNC_PREAMBLE.format(short_name=name_path[-1], display_name=disp_name, state_id=my_id_num)

        parent_run_ptr = parent_ptrs[0] if parent_ptrs else None
        parent_hist_ptr = parent_ptrs[1] if parent_ptrs else None

        if parent_run_ptr:
            self.outputs['macros'].append(f"#define IN_STATE_{my_c_name} (ctx->{parent_run_ptr} == state_{my_c_name}_run)")

        hist_save_code = f"ctx->{parent_hist_ptr} = state_{my_c_name}_entry;" if parent_hist_ptr else ""
        set_parent_code = f"ctx->{parent_run_ptr} = state_{my_c_name}_run;" if parent_run_ptr else ""

        trans_code = ""
        for t in data.get('transitions', []):
            trans_code += self.emit_transition_logic(name_path, t, 1)

        is_composite = 'states' in data
        is_parallel = data.get('parallel', False)
        
        h_entry = self.hooks.get('entry', '')
        h_run = self.hooks.get('run', '')
        h_exit = self.hooks.get('exit', '')

        if is_composite:
            if is_parallel:
                p_entries, p_exits, p_ticks = "", "", ""
                for child_name, child_data in data['states'].items():
                    child_path = name_path + [child_name]
                    region_ptr = f"ptr_{flatten_name(child_path, '_')}"
                    
                    init_leaf = flatten_name(child_path + [child_data['initial']], "_")
                    p_entries += f"    state_{init_leaf}_entry(ctx);\n"
                    p_ticks += f"    if (ctx->{region_ptr}) ctx->{region_ptr}(ctx);\n"
                    p_exits += f"    // Implicit exit {child_name}\n"
                    
                    self.recurse(child_path, child_data, (region_ptr, None))

                func_body = COMPOSITE_AND_TEMPLATE.format(
                    c_name=my_c_name, state_id=my_id_num, preamble=preamble,
                    hook_entry=h_entry, hook_run=h_run, hook_exit=h_exit,
                    entry=data.get('entry', ''), exit=data.get('exit', ''), run=data.get('run', ''),
                    transitions=trans_code, set_parent=set_parent_code,
                    parallel_entries=p_entries, parallel_exits=p_exits, parallel_ticks=p_ticks,
                    history_save=hist_save_code
                )
            else:
                my_ptr = f"ptr_{my_c_name}"
                my_hist = f"hist_{my_c_name}"
                self.outputs['context_ptrs'].append(f"StateFunc {my_ptr};")
                self.outputs['context_ptrs'].append(f"StateFunc {my_hist};")
                
                init_target = flatten_name(name_path + [data['initial']], "_")
                hist_bool = "true" if data.get('history', False) else "false"

                func_body = COMPOSITE_OR_TEMPLATE.format(
                    c_name=my_c_name, state_id=my_id_num, preamble=preamble,
                    hook_entry=h_entry, hook_run=h_run, hook_exit=h_exit,
                    entry=data.get('entry', ''), exit=data.get('exit', ''), run=data.get('run', ''),
                    transitions=trans_code, history=hist_bool,
                    self_ptr=my_ptr, self_hist_ptr=my_hist,
                    initial_target=init_target, history_save=hist_save_code,
                    set_parent=set_parent_code
                )
                
                for child_name, child_data in data['states'].items():
                    self.recurse(name_path + [child_name], child_data, (my_ptr, my_hist))
        else:
            func_body = LEAF_TEMPLATE.format(
                c_name=my_c_name, state_id=my_id_num, preamble=preamble,
                hook_entry=h_entry, hook_run=h_run, hook_exit=h_exit,
                entry=data.get('entry', ''), exit=data.get('exit', ''), run=data.get('run', ''),
                transitions=trans_code, history_save=hist_save_code,
                parent_ptr=parent_run_ptr
            )

        self.outputs['functions'].append(func_body)
        self.outputs['forwards'].append(f"void state_{my_c_name}_entry(SM_Context* ctx);")
        self.outputs['forwards'].append(f"void state_{my_c_name}_run(SM_Context* ctx);")
        self.outputs['forwards'].append(f"void state_{my_c_name}_exit(SM_Context* ctx);")

    def gen_inspector(self, name_path, data, ptr_name_in_struct):
        my_c_name = flatten_name(name_path, "_")
        func_name = f"inspect_{my_c_name}"
        disp_name = "" if name_path == ['root'] else "/" + name_path[-1]

        body = f"void {func_name}(SM_Context* ctx, char* buf, size_t* off, size_t max) {{\n"
        if disp_name: body += f"    safe_strcat(buf, \"{disp_name}\", off, max);\n"

        is_composite = 'states' in data
        if is_composite:
            if data.get('parallel', False):
                body += f"    safe_strcat(buf, \"[\", off, max);\n"
                children = list(data['states'].items())
                for i, (child_name, child_data) in enumerate(children):
                    child_path = name_path + [child_name]
                    child_func = f"inspect_{flatten_name(child_path, '_')}"
                    region_ptr = f"ptr_{flatten_name(child_path, '_')}"
                    self.gen_inspector(child_path, child_data, region_ptr)
                    body += f"    {child_func}(ctx, buf, off, max);\n"
                    if i < len(children)-1: body += "    safe_strcat(buf, \",\", off, max);\n"
                body += f"    safe_strcat(buf, \"]\", off, max);\n"
            else:
                my_ptr = f"ptr_{my_c_name}"
                for child_name, child_data in data['states'].items():
                    self.gen_inspector(name_path + [child_name], child_data, my_ptr)
                
                first = True
                for child_name, child_data in data['states'].items():
                    c_name = flatten_name(name_path + [child_name], "_")
                    else_txt = "else " if not first else ""
                    body += f"    {else_txt}if (ctx->{my_ptr} == state_{c_name}_run) inspect_{c_name}(ctx, buf, off, max);\n"
                    first = False
        
        body += "}\n"
        self.inspect_list.append(body)
