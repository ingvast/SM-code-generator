from statemachine import StateMachine

print("--- Starting Python State Machine ---")

sm = StateMachine()
print(sm.get_state_str())

while sm.is_running():
    sm.tick()
    sm.ctx.counter += 1
    print(f"{sm.ctx.counter:02d}: {sm.get_state_str()}")
