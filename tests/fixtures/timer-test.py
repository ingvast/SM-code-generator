from statemachine import StateMachine

sm = StateMachine()

while sm.is_running():
    sm.ctx.now = round(sm.ctx.now + 0.01, 2)
    sm.tick()
    print(f"t={sm.ctx.now:.2f} state={sm.get_state_str()}")
