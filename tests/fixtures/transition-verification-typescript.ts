import { StateMachine } from "./statemachine";

console.log("--- Starting TypeScript State Machine ---");

const sm = new StateMachine();
console.log(sm.getStateStr());

while (sm.isRunning()) {
    sm.tick();
    sm.ctx.counter += 1;
    console.log(`${String(sm.ctx.counter).padStart(2, '0')}: ${sm.getStateStr()}`);
}
