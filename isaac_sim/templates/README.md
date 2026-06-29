# isaac_sim/templates — scene templates (robot × environment)

Templates decouple **robot** from **environment** so the same robot works in any
scene with no pose math. Three pieces compose:

| Piece | Lives in | Provides |
|---|---|---|
| Robot defaults | `agents/core/assets/catalog.yaml` (per robot) | `start_z` (height), `drive`, `usd` |
| Environment template | `environments.yaml` | `scene` USD + named **anchors** (x,y spawn points) |
| Composite template | `<name>.yaml` | an environment + a list of robots@anchors (a fleet) |

`claw` resolves a launch from any of three forms (most templated → most explicit):

```bash
claw open --template warehouse_g1                 # named bundle (env + robots)
claw open --env warehouse --robot unitree_g1      # compose: env anchor + robot height
claw open --env warehouse --robot spot --anchor dock
claw open --scene warehouse.usd --robot unitree_h1 --z 1.05   # fully explicit (legacy)
```

**Same robot, different environment "just works":** because the robot's height
comes from the catalog and the position comes from the environment's anchor, you
change only `--env`:
```bash
claw open --env warehouse --robot unitree_g1
claw open --env office    --robot unitree_g1      # once office is added below
```

## Add an environment
Add a block to `environments.yaml` with its `scene` (a file in
`../scenes/`) and anchors. Every existing robot template immediately works in it.

## Add a composite template
Drop `<name>.yaml`: an `environment:` plus a `robots:` list, each `{robot, anchor,
[x,y,z overrides]}`. Multi-robot templates are fleets (see `warehouse_fleet.yaml`).

## List what's available
```bash
claw templates
```
