from statemachine import StateMachine

sm = StateMachine()
print(f"00: {sm.get_state_str()}")

while sm.is_running() and sm.ctx.step < 12:
    sm.ctx.step += 1
    sm.tick()
    print(f"{sm.ctx.step:02d}: {sm.get_state_str()}")
print("done")
