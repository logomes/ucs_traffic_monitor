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

@test "utm::confirm returns 0 for 'Y'" {
    run bash -c "source '$LIB_PATH'; printf 'Y' | utm::confirm 'go?'"
    [ "$status" -eq 0 ]
}

@test "utm::confirm returns 1 for 'n'" {
    run bash -c "source '$LIB_PATH'; printf 'n' | utm::confirm 'go?'"
    [ "$status" -eq 1 ]
}

@test "utm::confirm returns 1 for empty input" {
    run bash -c "source '$LIB_PATH'; printf '' | utm::confirm 'go?'"
    [ "$status" -eq 1 ]
}

@test "utm::log writes to stderr in expected format" {
    run bash -c "source '$LIB_PATH'; utm::log info 'hello' 2>&1 1>/dev/null"
    [ "$status" -eq 0 ]
    [[ "$output" =~ \[[0-9-]+\ [0-9:]+\]\ INFO:\ hello ]]
}

@test "utm::log uppercases level" {
    run bash -c "source '$LIB_PATH'; utm::log warning 'careful' 2>&1 1>/dev/null"
    [[ "$output" =~ WARNING ]]
}

@test "UTM_DASHBOARDS has 8 entries" {
    run bash -c "source '$LIB_PATH'; echo \${#UTM_DASHBOARDS[@]}"
    [ "$status" -eq 0 ]
    [ "$output" = "8" ]
}

@test "UTM_DASHBOARDS contains 'locations' key" {
    run bash -c "source '$LIB_PATH'; echo \${UTM_DASHBOARDS[locations]}"
    [ "$output" = "ri2OFp4Wz" ]
}

@test "utm::require_jq succeeds when jq is present" {
    run bash -c "source '$LIB_PATH'; utm::require_jq; echo ok"
    [ "$status" -eq 0 ]
    [[ "$output" =~ ok ]]
}

@test "utm::require_jq fails when jq is absent" {
    # Run the function with PATH that excludes jq.
    run bash -c "source '$LIB_PATH'; PATH=/nonexistent utm::require_jq"
    [ "$status" -eq 1 ]
}
