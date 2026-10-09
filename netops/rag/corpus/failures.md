# NetOps Copilot Runbooks

## OSPF Area Mismatch
If `show ip ospf neighbor` shows no neighbors, check if the interface is in the wrong area (e.g., area 1 instead of area 0).
Fix: `interface ethX`, `no ip ospf area`, `ip ospf area 0`.

## OSPF Passive Interface
If an interface is missing from OSPF neighbors, it might be passive.
Fix: `router ospf`, `no passive-interface ethX`.
