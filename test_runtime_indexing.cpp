// Quick compile test for runtime indexing
#include "examples/intro/generated/messaging/msg_types.hpp"

int main() {
    // Compile-time access (existing pattern)
    auto fault_id = msgs.drive.fault;
    auto overtemp_id = msgs.drive.overtemp;
    
    // Runtime indexing (new pattern)
    auto view = msgs.drive[0];
    auto fault_from_view = view.fault();
    auto overtemp_from_view = view.overtemp();
    
    // Verify they're the same
    static_assert(msgs.drive.fault == MessageId(0));
    static_assert(msgs.drive.overtemp == MessageId(1));
    
    // Check that operator[] returns a view with correct base_msg_id
    // msgs.drive[0] should have base_msg_id = 0
    // msgs.drive[1] should have base_msg_id = 2 (stride=2)
    
    return 0;
}
