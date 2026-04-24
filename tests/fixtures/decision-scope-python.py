from statemachine import StateMachine

sm = StateMachine()
print(f"00: {sm.get_state_str()}")

while sm.is_running():
    sm.ctx.counter += 1
    sm.tick()
    print(f"{sm.ctx.counter:02d}: {sm.get_state_str()}")
print("done")
