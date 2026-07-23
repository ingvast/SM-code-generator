import { StateMachine } from "./statemachine";

console.log("--- ortho-nested-entry ---");

const sm = new StateMachine();
console.log(`00: ${sm.getStateStr()}`);

while (sm.isRunning() && sm.ctx.counter < 6) {
    sm.tick();
    sm.ctx.counter += 1;
    console.log(`${String(sm.ctx.counter).padStart(2, '0')}: ${sm.getStateStr()}`);
}
