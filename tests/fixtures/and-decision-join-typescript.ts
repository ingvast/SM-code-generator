import { StateMachine } from "./statemachine";

const sm = new StateMachine();
console.log(`00: ${sm.getStateStr()}`);

while (sm.isRunning()) {
    sm.ctx.step += 1;
    sm.tick();
    console.log(`${String(sm.ctx.step).padStart(2, '0')}: ${sm.getStateStr()}`);
}
console.log("done");
