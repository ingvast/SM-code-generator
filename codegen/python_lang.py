from .base_lang import BaseGenerator
from .common import flatten_name
import re


class PythonGenerator(BaseGenerator):

    # Python has no semicolons, no braces, uses True/False, # comments
    STMT_END = ""
    BLOCK_CLOSE = ""
    TRUE_LIT = "True"
    FALSE_LIT = "False"
    COMMENT = "#"
    LINE_SEP = "\n"

    FUNC_PREAMBLE = """\
state_name = "{short_name}"
state_full_name = "{display_name}"
time = ctx.now - ctx.state_timers[{state_id}]
"""

    LEAF_TEMPLATE = """
def state_{c_name}_start(ctx):
    ctx.state_timers[{state_id}] = ctx.now
    {preamble}
    {hook_entry}
    {entry}
    {set_parent}

def state_{c_name}_entry(ctx):
    state_{c_name}_start(ctx)

def state_{c_name}_exit(ctx):
    {preamble}
    {hook_exit}
    {exit}
    {clear_parent}

def state_{c_name}_do(ctx):
    {preamble}
    {hook_do}
    {transitions}
    {do}
"""

    COMPOSITE_OR_TEMPLATE = """
def state_{c_name}_start(ctx):
    ctx.state_timers[{state_id}] = ctx.now
    {preamble}
    {hook_entry}
    {entry}
    {set_parent}

def state_{c_name}_entry(ctx):
    state_{c_name}_start(ctx)
    if ({history}) and ctx.{self_hist_ptr} is not None:
        ctx.{self_hist_ptr}(ctx)
    else:
        state_{initial_target}_entry(ctx)

def state_{c_name}_exit(ctx):
    {preamble}
    # RECURSIVE EXIT: Kill active child first
    if ctx.{self_exit_ptr} is not None:
        ctx.{self_exit_ptr}(ctx)

    {hook_exit}
    {exit}
    {clear_parent}

def state_{c_name}_do(ctx):
    {preamble}
    {hook_do}
    {transitions}
    {do}

    # Tick active child
    if ctx.{self_ptr} is not None:
        ctx.{self_ptr}(ctx)
"""

    COMPOSITE_AND_TEMPLATE = """
def state_{c_name}_start(ctx):
    ctx.state_timers[{state_id}] = ctx.now
    {preamble}
    {hook_entry}
    {entry}
    {set_parent}

def state_{c_name}_entry(ctx):
    state_{c_name}_start(ctx)
    {parallel_entries}

def state_{c_name}_exit(ctx):
    {preamble}
    # RECURSIVE EXIT
    {parallel_exits}

    {hook_exit}
    {exit}
    {clear_parent}

def state_{c_name}_do(ctx):
    {preamble}
    {hook_do}
    {transitions}
    {do}

    # Safety: Stop if we are exited OR if any transition fired globally
    {safety_check}

    {parallel_ticks}
"""

    INSPECTOR_TEMPLATE = """
def inspect_{c_name}(ctx, buf):
    {push_name}
    {content}
"""

    def __init__(self, data):
        super().__init__(data)

    def format_template(self, template, **kwargs):
        """Indent-aware template formatting for Python.

        For multi-line values substituted at line-leading placeholders:
        1. Find the value's base indentation (minimum non-empty line indent)
        2. Strip that base indent from all lines
        3. Add the template placeholder's indent to all lines
        4. Strip indent from first line (template provides it via {placeholder})
        This preserves relative indentation within the value.
        """
        import re as _re

        # Find the indent level for each placeholder that starts a line
        indent_map = {}
        for match in _re.finditer(r'^([ \t]*)\{(\w+)\}', template, flags=_re.MULTILINE):
            indent_map[match.group(2)] = match.group(1)

        # Pre-indent multi-line values
        adjusted = {}
        for key, value in kwargs.items():
            value = str(value)
            if key in indent_map and '\n' in value:
                target_indent = indent_map[key]
                lines = value.split('\n')

                # Find base indent (minimum of non-empty lines)
                base_indent = None
                for line in lines:
                    if line.strip():
                        leading = len(line) - len(line.lstrip())
                        if base_indent is None or leading < base_indent:
                            base_indent = leading
                if base_indent is None:
                    base_indent = 0

                # Re-indent: strip base, add target
                indented_lines = []
                for line in lines:
                    if line.strip():
                        indented_lines.append(target_indent + line[base_indent:])
                    else:
                        indented_lines.append('')

                # First line: strip indent (template provides it)
                if indented_lines and indented_lines[0].strip():
                    indented_lines[0] = indented_lines[0].lstrip()

                adjusted[key] = '\n'.join(indented_lines)
            else:
                adjusted[key] = value

        return template.format(**adjusted)

    # --- Python-specific syntax hooks ---

    def fmt_if_open(self, cond):
        return f"if {cond}:"

    def fmt_elif_open(self, cond):
        return f"elif {cond}:"

    def fmt_str_var(self, name, value):
        return f'{name} = "{value}"'

    def fmt_set_flag(self, flag, value):
        return f"ctx.{flag} = {value}"

    def fmt_opt_call(self, ptr):
        return f"if ctx.{ptr} is not None: ctx.{ptr}(ctx)"

    def fmt_set_fn(self, ptr, fn_name):
        return f"ctx.{ptr} = {fn_name}"

    def fmt_clear_fn(self, ptr):
        return f"ctx.{ptr} = None"

    def fmt_ptr_decl(self, name):
        # Not needed as a separate declaration in Python
        return ""

    def fmt_ptr_init(self, name):
        return f"self.{name} = None"

    def fmt_ptr_eq(self, ptr, fn_name):
        return f"ctx.{ptr} == {fn_name}"

    def fmt_safety_check(self, c_name, has_parent):
        if has_parent:
            return f"if not ctx.in_state_{c_name}() or ctx.transition_fired: return"
        else:
            return f"if ctx.transition_fired: return"

    def fmt_guard_expand(self, guard_str):
        return re.sub(r'IN_STATE\(([\w_]+)\)', r'ctx.in_state_\1()', guard_str)

    def gen_in_state_impl(self, c_name, parent_run_ptr):
        method = f"""
    def in_state_{c_name}(self):
        return self.{parent_run_ptr} == state_{c_name}_do
"""
        self.outputs['impls'].append(method)

    def fmt_opt_call_region_exit(self, region_exit_ptr):
        return f"if ctx.{region_exit_ptr} is not None: ctx.{region_exit_ptr}(ctx)"

    def fmt_tick_child(self, child_c_name):
        return f"state_{child_c_name}_do(ctx)"

    def fmt_inspect_push(self, text):
        return f'buf.append("{text}")'

    def fmt_inspect_call(self, func_name):
        return f"{func_name}(ctx, buf)"

    def fmt_inspect_ptr_eq(self, ptr, fn_name):
        return f"ctx.{ptr} == {fn_name}"

    def _indent_block(self, text, indent):
        """Indent a multi-line block of text."""
        lines = text.rstrip().splitlines()
        return "\n".join(indent + line if line.strip() else "" for line in lines)

    def assemble_output(self):
        context_init = self.data.get('context_init', '')

        # Build context pointer inits (indented for __init__)
        ptr_inits = "\n".join(
            "        " + init for init in self.outputs['context_init'] if init
        )

        # Indent context_init code
        context_init_indented = self._indent_block(context_init, "        ") if context_init else ""

        # Build the in_state methods (indented for class body)
        in_state_methods = ""
        for impl in self.outputs['impls']:
            # Each impl already has 4-space indent for method body; ensure it's correct
            in_state_methods += impl

        source = f"""\
# Generated State Machine (Python)
# Do not edit - generated by sm-compiler

TOTAL_STATES = {self.state_counter}

# --- User Includes ---
{self.includes}

class Context:
    def __init__(self):
        ctx = self
        self.owner = None
        self.now = 0.0
        self.state_timers = [0.0] * TOTAL_STATES
        self.transition_fired = False
        self.terminated = False

        # Hierarchy Pointers
{ptr_inits}

        # User Context Init
{context_init_indented}
{in_state_methods}

# --- State Logic ---
"""

        source += "\n".join(self.outputs['functions'])
        source += "\n# --- Inspection ---\n" + "\n".join(self.inspect_list)

        source += f"""

class StateMachine:
    def __init__(self):
        self.ctx = Context()
        self.root = None
        state_root_entry(self.ctx)
        self.root = state_root_do

    def tick(self):
        self.ctx.transition_fired = False
        if self.root is not None:
            self.root(self.ctx)
            if self.ctx.terminated:
                self.root = None

    def is_running(self):
        return self.root is not None

    def get_state_str(self):
        buf = []
        if self.root is not None:
            inspect_root(self.ctx, buf)
        else:
            buf.append("FINISHED")
        return "".join(buf)
"""

        return source, ""
