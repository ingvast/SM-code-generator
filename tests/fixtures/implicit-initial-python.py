from statemachine import StateMachine

print("--- implicit-initial ---")

sm = StateMachine()
print(f"00: {sm.get_state_str()}")

while sm.is_running() and sm.ctx.counter < 8:
    sm.tick()
    sm.ctx.counter += 1
    print(f"{sm.ctx.counter:02d}: {sm.get_state_str()}")
