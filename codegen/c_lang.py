from .base_lang import BaseGenerator
from .common import flatten_name
import re

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
    bool transition_fired;
    bool terminated;

    // Hierarchy Pointers
    %s

    // User Context Fields
    %s
};

typedef struct {
    SM_Context ctx;
    StateFunc root;
} StateMachine;

void sm_init(StateMachine* sm);
void sm_tick(StateMachine* sm);
bool sm_is_running(StateMachine* sm);
void sm_get_state_str(StateMachine* sm, char* buffer, size_t max_len);

// --- IN_STATE Macros ---
%s

#endif
"""

SOURCE_TOP = """
#include "%s"

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


class CGenerator(BaseGenerator):

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
    {entry}
    {set_parent}
}}

void state_{c_name}_entry(SM_Context* ctx) {{
    state_{c_name}_start(ctx);
}}

void state_{c_name}_exit(SM_Context* ctx) {{
    {preamble}
    {hook_exit}
    {exit}
    {clear_parent}
}}

void state_{c_name}_do(SM_Context* ctx) {{
    {preamble}
    {hook_do}
    {transitions}
    {do}
}}
"""

    COMPOSITE_OR_TEMPLATE = """
void state_{c_name}_start(SM_Context* ctx) {{
    ctx->state_timers[{state_id}] = ctx->now;
    {preamble}
    {hook_entry}
    {entry}
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

void state_{c_name}_exit(SM_Context* ctx) {{
    {preamble}
    // RECURSIVE EXIT: Kill active child first
    if (ctx->{self_exit_ptr}) ctx->{self_exit_ptr}(ctx);

    {hook_exit}
    {exit}
    {clear_parent}
}}

void state_{c_name}_do(SM_Context* ctx) {{
    {preamble}
    {hook_do}
    {transitions}
    {do}

    // Tick active child
    if (ctx->{self_ptr}) ctx->{self_ptr}(ctx);
}}
"""

    COMPOSITE_AND_TEMPLATE = """
void state_{c_name}_start(SM_Context* ctx) {{
    ctx->state_timers[{state_id}] = ctx->now;
    {preamble}
    {hook_entry}
    {entry}
    {set_parent}
}}

void state_{c_name}_entry(SM_Context* ctx) {{
    state_{c_name}_start(ctx);
    {parallel_entries}
}}

void state_{c_name}_exit(SM_Context* ctx) {{
    {preamble}
    // RECURSIVE EXIT
    {parallel_exits}

    {hook_exit}
    {exit}
    {clear_parent}
}}

void state_{c_name}_do(SM_Context* ctx) {{
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
void inspect_{c_name}(SM_Context* ctx, char* buf, size_t* off, size_t max) {{
    {push_name}
    {content}
}}
"""

    def __init__(self, data, header_name="statemachine.h"):
        super().__init__(data)
        self.header_name = header_name
        self.forwards = []
        self.macros = []

    # --- C-specific syntax hooks ---

    def fmt_if_open(self, cond):
        return f"if ({cond}) {{"

    def fmt_str_var(self, name, value):
        return f'const char* {name} = "{value}";'

    def fmt_set_flag(self, flag, value):
        return f"ctx->{flag} = {value};"

    def fmt_opt_call(self, ptr):
        return f"if (ctx->{ptr}) ctx->{ptr}(ctx);"

    def fmt_set_fn(self, ptr, fn_name):
        return f"ctx->{ptr} = {fn_name};"

    def fmt_clear_fn(self, ptr):
        return f"ctx->{ptr} = NULL;"

    def fmt_ptr_decl(self, name):
        return f"StateFunc {name};"

    def fmt_ptr_init(self, name):
        # C uses memset to zero-init, so no explicit init needed
        return ""

    def fmt_ptr_eq(self, ptr, fn_name):
        return f"ctx->{ptr} == {fn_name}"

    def fmt_safety_check(self, c_name, has_parent):
        if has_parent:
            return f"if (!IN_STATE_{c_name} || ctx->transition_fired) return;"
        else:
            return f"if (ctx->transition_fired) return;"

    def fmt_guard_expand(self, guard_str):
        # In C, IN_STATE(X) expands to the macro IN_STATE_X
        return re.sub(r'IN_STATE\(([\w_]+)\)', r'IN_STATE_\1', guard_str)

    def gen_in_state_impl(self, c_name, parent_run_ptr):
        # C uses macros instead of impl methods
        self.macros.append(f"#define IN_STATE_{c_name} (ctx->{parent_run_ptr} == state_{c_name}_do)")

    def fmt_opt_call_region_exit(self, region_exit_ptr):
        return f"if (ctx->{region_exit_ptr}) ctx->{region_exit_ptr}(ctx);"

    def fmt_tick_child(self, child_c_name):
        return f"state_{child_c_name}_do(ctx);"

    def fmt_inspect_push(self, text):
        return f'safe_strcat(buf, "{text}", off, max);'

    def fmt_inspect_call(self, func_name):
        return f"{func_name}(ctx, buf, off, max);"

    def fmt_inspect_ptr_eq(self, ptr, fn_name):
        return f"ctx->{ptr} == {fn_name}"

    # --- Override recurse to also generate forward declarations ---

    def recurse(self, name_path, data, parent_ptrs):
        super().recurse(name_path, data, parent_ptrs)
        my_c_name = flatten_name(name_path, "_")
        self.forwards.append(f"void state_{my_c_name}_start(SM_Context* ctx);")
        self.forwards.append(f"void state_{my_c_name}_entry(SM_Context* ctx);")
        self.forwards.append(f"void state_{my_c_name}_exit(SM_Context* ctx);")
        self.forwards.append(f"void state_{my_c_name}_do(SM_Context* ctx);")

    def assemble_output(self):
        user_context = self.data.get('context', '')
        context_init = self.data.get('context_init', '')

        header = HEADER % (
            self.state_counter,
            "\n".join(self.forwards),
            "\n    ".join(self.outputs['context_ptrs']),
            user_context,
            "\n".join(self.macros)
        )

        source = SOURCE_TOP % (self.header_name, self.includes) + "\n".join(self.outputs['functions'])
        source += "\n// --- Inspection ---\n" + "\n".join(self.inspect_list)

        source += f"""
void sm_init(StateMachine* sm) {{
    memset(&sm->ctx, 0, sizeof(sm->ctx));
    sm->ctx.owner = sm;
    {context_init}
    state_root_entry(&sm->ctx);
    sm->root = state_root_do;
}}
void sm_tick(StateMachine* sm) {{
    sm->ctx.transition_fired = false;
    if (sm->root) {{
        sm->root(&sm->ctx);
        if (sm->ctx.terminated) {{
            sm->root = NULL;
        }}
    }}
}}
bool sm_is_running(StateMachine* sm) {{
    return sm->root != NULL;
}}
void sm_get_state_str(StateMachine* sm, char* buffer, size_t max_len) {{
    size_t offset = 0;
    buffer[0] = '\\0';
    if (sm->root) {{
        inspect_root(&sm->ctx, buffer, &offset, max_len);
    }} else {{
        size_t len = strlen("FINISHED");
        if (len < max_len) strcpy(buffer, "FINISHED");
    }}
}}
"""
        return header, source
