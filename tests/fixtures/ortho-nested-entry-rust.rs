mod statemachine;

fn main() {
    println!("--- ortho-nested-entry ---");

    let mut sm = statemachine::StateMachine::new();
    println!("00: {}", sm.get_state_str());

    while sm.is_running() && sm.ctx.counter < 6 {
        sm.tick();
        sm.ctx.counter += 1;
        println!("{:02}: {}", sm.ctx.counter, sm.get_state_str());
    }
}
