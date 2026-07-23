#include "statemachine.h"
#include <stdio.h>

int main(void) {
    StateMachine sm;
    sm_init(&sm);

    char state_buf[256];
    sm_get_state_str(&sm, state_buf, sizeof(state_buf));
    printf("00: %s\n", state_buf);

    while (sm_is_running(&sm)) {
        sm.ctx.step += 1;
        sm_tick(&sm);
        sm_get_state_str(&sm, state_buf, sizeof(state_buf));
        printf("%02d: %s\n", sm.ctx.step, state_buf);
    }
    printf("done\n");
    return 0;
}
