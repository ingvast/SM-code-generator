from statemachine import StateMachine

sm = StateMachine()
print(f"00: {sm.get_state_str()}")

while sm.is_running():
    sm.ctx.now = round(sm.ctx.now + 1.0, 2)
    sm.tick()
    print(f"{int(sm.ctx.now):02d}: {sm.get_state_str()}")
print("done")
