from .base_lang import BaseGenerator
from .common import flatten_name

HEADER = """
#![allow(unused_variables)]
#![allow(dead_code)]
#![allow(non_snake_case)]

// --- User Includes / Context Types ---
%s

pub struct Context {
    pub now: f64,
    pub state_timers: [f64; %d],
    pub transition_fired: bool,
    pub terminated: bool,

    // Hierarchy Pointers (Option<fn>)
    %s

    // User Context Fields
    %s
}

// Function Pointer Type
type StateFn = fn(&mut Context);

pub struct StateMachine {
    pub ctx: Context,
    pub root: Option<StateFn>,
}

impl StateMachine {
    pub fn new() -> Self {
        let ctx = Context {
            now: 0.0,
            state_timers: [0.0; %d],
            transition_fired: false,
            terminated: false,

            // Init Hierarchy Pointers
            %s

            // Init User Context
            %s
        };

        let mut sm = StateMachine {
            ctx,
            root: None,
        };

        // Start Machine
        state_root_entry(&mut sm.ctx);
        sm.root = Some(state_root_do);
        sm
    }

    pub fn tick(&mut self) {
        self.ctx.transition_fired = false;

        if let Some(do_fn) = self.root {
            do_fn(&mut self.ctx);

            if self.ctx.terminated {
                self.root = None;
            }
        }
    }

    pub fn is_running(&self) -> bool {
        self.root.is_some()
    }

    pub fn get_state_str(&self) -> String {
        let mut buffer = String::new();
        if self.root.is_some() {
             inspect_root(&self.ctx, &mut buffer);
        } else {
             buffer.push_str("FINISHED");
        }
        buffer
    }
}

// --- Helper Macros/Methods ---
impl Context {
    %s
}

// --- State Logic ---
"""


class RustGenerator(BaseGenerator):

    FUNC_PREAMBLE = """
    let state_name = "{short_name}";
    let state_full_name = "{display_name}";
    let time = ctx.now - ctx.state_timers[{state_id}];
"""

    LEAF_TEMPLATE = """
fn state_{c_name}_start(ctx: &mut Context) {{
    ctx.state_timers[{state_id}] = ctx.now;
    {preamble}
    {hook_entry}
    {entry}
    {set_parent}
}}

fn state_{c_name}_entry(ctx: &mut Context) {{
    state_{c_name}_start(ctx);
}}

fn state_{c_name}_exit(ctx: &mut Context) {{
    {preamble}
    {hook_exit}
    {exit}
    {clear_parent}
}}

fn state_{c_name}_do(ctx: &mut Context) {{
    {preamble}
    {hook_do}
    {transitions}
    {do}
}}
"""

    COMPOSITE_OR_TEMPLATE = """
fn state_{c_name}_start(ctx: &mut Context) {{
    ctx.state_timers[{state_id}] = ctx.now;
    {preamble}
    {hook_entry}
    {entry}
    {set_parent}
}}

fn state_{c_name}_entry(ctx: &mut Context) {{
    state_{c_name}_start(ctx);
    if ({history}) && ctx.{self_hist_ptr}.is_some() {{
        let hist_fn = ctx.{self_hist_ptr}.unwrap();
        hist_fn(ctx);
    }} else {{
        state_{initial_target}_entry(ctx);
    }}
}}

fn state_{c_name}_exit(ctx: &mut Context) {{
    {preamble}
    // RECURSIVE EXIT: Kill active child first
    if let Some(child_exit) = ctx.{self_exit_ptr} {{
        child_exit(ctx);
    }}

    {hook_exit}
    {exit}
    {clear_parent}
}}

fn state_{c_name}_do(ctx: &mut Context) {{
    {preamble}
    {hook_do}
    {transitions}
    {do}

    // Tick active child
    if let Some(child_do) = ctx.{self_ptr} {{
        child_do(ctx);
    }}
}}
"""

    COMPOSITE_AND_TEMPLATE = """
fn state_{c_name}_start(ctx: &mut Context) {{
    ctx.state_timers[{state_id}] = ctx.now;
    {preamble}
    {hook_entry}
    {entry}
    {set_parent}
}}

fn state_{c_name}_entry(ctx: &mut Context) {{
    state_{c_name}_start(ctx);
    {parallel_entries}
}}

fn state_{c_name}_exit(ctx: &mut Context) {{
    {preamble}
    // RECURSIVE EXIT
    {parallel_exits}

    {hook_exit}
    {exit}
    {clear_parent}
}}

fn state_{c_name}_do(ctx: &mut Context) {{
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
fn inspect_{c_name}(ctx: &Context, buf: &mut String) {{
    {push_name}
    {content}
}}
"""

    def assemble_output(self):
        user_init = self.data.get('context_init', '')

        header = HEADER % (
            self.includes,
            self.state_counter,
            "\n    ".join(self.outputs['context_ptrs']),
            self.data.get('context', ''),
            self.state_counter,
            "\n            ".join(self.outputs['context_init']),
            user_init,
            "\n    ".join(self.outputs['impls'])
        )

        source = "\n".join(self.outputs['functions'])
        source += "\n// --- Inspection ---\n" + "\n".join(self.inspect_list)

        return header + source, ""
