/* effort.c — see effort.h. */
#include "effort.h"

#include <stddef.h>

#define EFFORT_LINE_STEADY "your hands are steady."
#define EFFORT_LINE_TIRED  "you are too tired for this."

static uint16_t above(uint16_t v, uint16_t floor) { return v > floor ? (uint16_t)(v - floor) : 0; }

uint16_t effort_skill(const EffortTask* t, const EffortBody* b) {
    (void)t;
    int s = (int)b->axis_value - EFFORT_SKILL_BASE;
    return s > 0 ? (uint16_t)(s * EFFORT_PER_SKILL) : 0;
}

uint16_t effort_available(const EffortTask* t, const EffortBody* b) {
    uint32_t a = (uint32_t)above(b->fuel, EFFORT_FUEL_FLOOR) + above(b->hp, EFFORT_HP_FLOOR) + effort_skill(t, b);
    return a > 0xFFFFu ? 0xFFFFu : (uint16_t)a;
}

uint16_t effort_required(const EffortTask* t) {
    uint8_t turns = t->turns ? t->turns : 1;
    return (uint16_t)(turns * t->difficulty);
}

bool effort_can(const EffortTask* t, const EffortBody* b) {
    return effort_available(t, b) >= effort_required(t);
}

const char* effort_odds_line(const EffortTask* t, const EffortBody* b) {
    return effort_can(t, b) ? EFFORT_LINE_STEADY : EFFORT_LINE_TIRED;
}

void effort_begin(EffortRun* r, const EffortTask* t, const EffortBody* b) {
    r->task = *t;
    if(r->task.turns == 0) r->task.turns = 1;
    r->turns_done = 0;
    r->skill_left = effort_skill(t, b);
    r->paid = 0;
}

EffortState effort_turn(EffortRun* r, EffortBody* b) {
    uint16_t required = effort_required(&r->task);
    uint16_t per = required / r->task.turns;
    uint16_t cost = (r->turns_done + 1 == r->task.turns) ? (uint16_t)(required - r->paid) : per;

    /* Skill first: a skilled player pays less from the body. */
    uint16_t from_skill = cost < r->skill_left ? cost : r->skill_left;
    r->skill_left -= from_skill;
    uint16_t body = (uint16_t)(cost - from_skill);

    /* Then health's share and fuel's, each covering the other's shortfall. */
    uint16_t want_hp = (uint16_t)((uint32_t)body * EFFORT_HP_SHARE / 100u);
    uint16_t want_fuel = (uint16_t)(body - want_hp);
    uint16_t hp_room = above(b->hp, EFFORT_HP_FLOOR), fuel_room = above(b->fuel, EFFORT_FUEL_FLOOR);
    uint16_t take_hp = want_hp < hp_room ? want_hp : hp_room;
    uint16_t take_fuel = want_fuel < fuel_room ? want_fuel : fuel_room;
    uint16_t short_hp = (uint16_t)(want_hp - take_hp), short_fuel = (uint16_t)(want_fuel - take_fuel);
    uint16_t more = (uint16_t)(fuel_room - take_fuel);
    uint16_t x = short_hp < more ? short_hp : more;
    take_fuel = (uint16_t)(take_fuel + x);
    short_hp = (uint16_t)(short_hp - x);
    more = (uint16_t)(hp_room - take_hp);
    x = short_fuel < more ? short_fuel : more;
    take_hp = (uint16_t)(take_hp + x);
    short_fuel = (uint16_t)(short_fuel - x);

    b->hp = (uint16_t)(b->hp - take_hp);
    b->fuel = (uint16_t)(b->fuel - take_fuel);
    r->paid = (uint16_t)(r->paid + from_skill + take_hp + take_fuel);
    if(short_hp || short_fuel) return EFFORT_SPENT;
    r->turns_done++;
    return r->turns_done >= r->task.turns ? EFFORT_DONE : EFFORT_GOING;
}
