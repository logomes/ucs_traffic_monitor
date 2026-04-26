#!/usr/bin/env bats

# Source the lib under test from the repo root regardless of cwd.
LIB_PATH="$BATS_TEST_DIRNAME/../../lib/utm-common.sh"

setup() {
    # shellcheck disable=SC1090
    source "$LIB_PATH"
}

@test "utm::confirm returns 0 for 'y'" {
    run bash -c "source '$LIB_PATH'; printf 'y' | utm::confirm 'go?'"
    [ "$status" -eq 0 ]
}
