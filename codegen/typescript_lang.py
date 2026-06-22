from .base_lang import BaseGenerator
from .common import flatten_name
import re


class TypeScriptGenerator(BaseGenerator):

    STMT_END = ";"
    BLOCK_CLOSE = "}"
    TRUE_LIT = "true"
    FALSE_LIT = "false"
    COMMENT = "//"
    LINE_SEP = "\n    "

    FUNC_PREAMBLE = """\
let state_name = "{short_name}";
    let state_full_name = "{display_name}";
    let time = ctx.now - ctx.stateTimers[{state_id}];
"""

    LEAF_TEMPLATE = """
function state_{c_name}_start(ctx: Context): void {{
    ctx.stateTimers[{state_id}] = ctx.now;
    {preamble}
    {hook_entry}
    {entry}
    {set_parent}
}}

function state_{c_name}_entry(ctx: Context): void {{
    state_{c_name}_start(ctx);
}}

function state_{c_name}_exit(ctx: Context): void {{
    {preamble}
    {hook_exit}
    {exit}
    {clear_parent}
}}

function state_{c_name}_do(ctx: Context): void {{
    {preamble}
    {hook_do}
    {transitions}
    {do}
}}
"""

    COMPOSITE_OR_TEMPLATE = """
function state_{c_name}_start(ctx: Context): void {{
    ctx.stateTimers[{state_id}] = ctx.now;
    {preamble}
    {hook_entry}
    {entry}
    {set_parent}
}}

function state_{c_name}_entry(ctx: Context): void {{
    state_{c_name}_start(ctx);
    if ({history} && ctx.{self_hist_ptr} !== null) {{
        ctx.{self_hist_ptr}!(ctx);
    }} else {{
        state_{initial_target}_entry(ctx);
    }}
}}

function state_{c_name}_exit(ctx: Context): void {{
    {preamble}
    // RECURSIVE EXIT: Kill active child first
    if (ctx.{self_exit_ptr} !== null) {{
        ctx.{self_exit_ptr}!(ctx);
    }}

    {hook_exit}
    {exit}
    {clear_parent}
}}

function state_{c_name}_do(ctx: Context): void {{
    {preamble}
    {hook_do}
    {transitions}
    {do}

    // Tick active child
    if (ctx.{self_ptr} !== null) {{
        ctx.{self_ptr}!(ctx);
    }}
}}
"""

    COMPOSITE_AND_TEMPLATE = """
function state_{c_name}_start(ctx: Context): void {{
    ctx.stateTimers[{state_id}] = ctx.now;
    {preamble}
    {hook_entry}
    {entry}
    {set_parent}
}}

function state_{c_name}_entry(ctx: Context): void {{
    state_{c_name}_start(ctx);
    {parallel_entries}
}}

function state_{c_name}_exit(ctx: Context): void {{
    {preamble}
    // RECURSIVE EXIT
    {parallel_exits}

    {hook_exit}
    {exit}
    {clear_parent}
}}

function state_{c_name}_do(ctx: Context): void {{
    {preamble}
    {hook_do}
    {transitions}
    {do}

    // Safety: Stop if we are exited OR if any transition fired globally
    {safety_check}

    {parallel_ticks}
}}
"""

    INSPECTOR_TEMPLATE = """
function inspect_{c_name}(ctx: Context, buf: string[]): void {{
    {push_name}
    {content}
}}
"""

    def __init__(self, data):
        super().__init__(data)

    # --- TypeScript-specific syntax hooks ---

    def fmt_if_open(self, cond):
        return f"if ({cond}) {{"

    def fmt_elif_open(self, cond):
        return f"else if ({cond}) {{"

    def fmt_str_var(self, name, value):
        return f'let {name} = "{value}";'

    def fmt_set_flag(self, flag, value):
        return f"ctx.{flag} = {value};"

    def fmt_opt_call(self, ptr):
        return f"if (ctx.{ptr} !== null) {{ ctx.{ptr}!(ctx); }}"

    def fmt_set_fn(self, ptr, fn_name):
        return f"ctx.{ptr} = {fn_name};"

    def fmt_clear_fn(self, ptr):
        return f"ctx.{ptr} = null;"

    def fmt_ptr_decl(self, name):
        return f"{name}: StateFn | null;"

    def fmt_ptr_init(self, name):
        return f"this.{name} = null;"

    def fmt_ptr_eq(self, ptr, fn_name):
        return f"ctx.{ptr} === {fn_name}"

    def fmt_safety_check(self, c_name, has_parent):
        if has_parent:
            return f"if (!ctx.inState_{c_name}() || ctx.transition_fired) {{ return; }}"
        else:
            return f"if (ctx.transition_fired) {{ return; }}"

    def fmt_guard_expand(self, guard_str):
        return re.sub(r'IN_STATE\(([\w_]+)\)', r'ctx.inState_\1()', guard_str)

    def fmt_time_since(self, state_id):
        return f"(ctx.now - ctx.stateTimers[{state_id}])"

    def gen_in_state_impl(self, c_name, parent_run_ptr):
        method = f"""
    inState_{c_name}(): boolean {{
        return this.{parent_run_ptr} === state_{c_name}_do;
    }}
"""
        self.outputs['impls'].append(method)

    def fmt_opt_call_region_exit(self, region_exit_ptr):
        return f"if (ctx.{region_exit_ptr} !== null) {{ ctx.{region_exit_ptr}!(ctx); }}"

    def fmt_tick_child(self, child_c_name):
        return f"state_{child_c_name}_do(ctx);"

    def fmt_inspect_push(self, text):
        return f'buf.push("{text}");'

    def fmt_inspect_call(self, func_name):
        return f"{func_name}(ctx, buf);"

    def fmt_inspect_ptr_eq(self, ptr, fn_name):
        return f"ctx.{ptr} === {fn_name}"

    def assemble_output(self):
        context_init = self.data.get('context_init', '')
        user_context = self.data.get('context', '')

        # Build context pointer declarations (for class body)
        ptr_decls = "\n".join(
            "    " + decl for decl in self.outputs['context_ptrs'] if decl
        )

        # Build context pointer inits (for constructor)
        ptr_inits = "\n".join(
            "        " + init for init in self.outputs['context_init'] if init
        )

        # Indent context_init code
        context_init_indented = self._indent_block(context_init, "        ") if context_init else ""

        # Indent user context fields
        user_context_indented = self._indent_block(user_context, "    ") if user_context else ""

        # Build the inState methods
        in_state_methods = ""
        for impl in self.outputs['impls']:
            in_state_methods += impl

        source = f"""\
// Generated State Machine (TypeScript)
// Do not edit - generated by sm-compiler

const TOTAL_STATES = {self.state_counter};
type StateFn = (ctx: Context) => void;

// --- User Includes ---
{self.includes}

class Context {{
    owner: any = null;
    now: number = 0;
    stateTimers: number[] = new Array(TOTAL_STATES).fill(0);
    transition_fired: boolean = false;
    terminated: boolean = false;

    // Hierarchy Pointers
{ptr_decls}

    // User Context Fields
{user_context_indented}

    constructor() {{
        let ctx = this;
{ptr_inits}

        // User Context Init
{context_init_indented}
    }}
{in_state_methods}}}

// --- State Logic ---
"""

        source += "\n".join(self.outputs['functions'])
        source += "\n// --- Inspection ---\n" + "\n".join(self.inspect_list)

        source += f"""

class StateMachine {{
    ctx: Context;
    private root: StateFn | null;

    constructor() {{
        this.ctx = new Context();
        this.root = null;
        state_root_entry(this.ctx);
        this.root = state_root_do;
    }}

    tick(): void {{
        this.ctx.transition_fired = false;
        if (this.root !== null) {{
            this.root(this.ctx);
            if (this.ctx.terminated) {{
                this.root = null;
            }}
        }}
    }}

    isRunning(): boolean {{
        return this.root !== null;
    }}

    getStateStr(): string {{
        let buf: string[] = [];
        if (this.root !== null) {{
            inspect_root(this.ctx, buf);
        }} else {{
            buf.push("FINISHED");
        }}
        return buf.join("");
    }}
}}

export {{ StateMachine, Context }};
"""

        return source, ""

    def _indent_block(self, text, indent):
        """Indent a multi-line block of text."""
        lines = text.rstrip().splitlines()
        return "\n".join(indent + line if line.strip() else "" for line in lines)
