mod statemachine;
use std::thread;
use std::time::{Duration, Instant};

fn main() {
    println!("--- Starting Rust State Machine ---");

    // 1. Initialize the machine
    let mut sm = statemachine::StateMachine::new();

    // 2. Start the clock
    let start_time = Instant::now();

    println!("{}", sm.get_state_str());

    while sm.is_running() {
        // 3. Update time (Seconds as f64)
        let elapsed = start_time.elapsed();
        sm.ctx.now = elapsed.as_secs_f64();

        // 4. Tick the machine
        sm.tick();
        sm.ctx.counter += 1;
        println!(
            "{:02}: {}",
            sm.ctx.counter,
            sm.get_state_str(),
            //sm.ctx.do_loop
        );

        // 5. Introspection (Optional debug print)
        // Note: We only print if the state string changes to avoid spam,
        // or you can rely on the hooks inside the machine.
        // let state_str = sm.get_state_str();
        // println!("Current: {}", state_str);

        // 6. Sleep to prevent 100% CPU usage
        thread::sleep(Duration::from_millis(10));
    }
}
