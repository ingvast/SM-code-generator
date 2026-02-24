#include "statemachine.h"
#include <stdio.h>
#include <unistd.h>

int main(void) {
    printf("--- Starting C State Machine ---\n");

    StateMachine sm;
    sm_init(&sm);

    char state_buf[256];
    sm_get_state_str(&sm, state_buf, sizeof(state_buf));
    printf("%s\n", state_buf);

    while (sm_is_running(&sm)) {
        sm_tick(&sm);
        sm.ctx.counter += 1;
        sm_get_state_str(&sm, state_buf, sizeof(state_buf));
        printf("%02d: %s\n", sm.ctx.counter, state_buf);
        usleep(10000);
    }

    return 0;
}
