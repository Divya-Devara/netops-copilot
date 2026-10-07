import os
from netops.tools import frr

def test_snapshot_apply_rollback():
    router = "r1"
    
    # 1. Take a snapshot
    snap_path = frr.snapshot(router)
    assert os.path.exists(snap_path)
    
    # 2. Define a harmless change (a dummy static route)
    change = frr.RouterChange(
        router=router,
        commands=["ip route 9.9.9.9/32 Null0"]
    )
    
    # 3. Apply the change
    frr.apply(change)
    
    # 4. Prove the change is live
    assert "9.9.9.9/32 Null0" in frr.running_config(router), "Change did not apply!"
    
    # 5. Roll it back using the snapshot
    frr.rollback(router, snap_path)
    
    # 6. Prove the change is gone
    assert "9.9.9.9/32 Null0" not in frr.running_config(router), "Rollback failed!"

