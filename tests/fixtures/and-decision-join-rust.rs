mod statemachine;

fn main() {
    let mut sm = statemachine::StateMachine::new();
    println!("00: {}", sm.get_state_str());

    while sm.is_running() {
        sm.ctx.step += 1;
        sm.tick();
        println!("{:02}: {}", sm.ctx.step, sm.get_state_str());
    }
    println!("done");
}
