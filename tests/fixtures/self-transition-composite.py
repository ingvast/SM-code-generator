from statemachine import StateMachine

sm = StateMachine()
while sm.is_running():
    sm.tick()
print("done")
