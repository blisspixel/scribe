package main

import (
	"bufio"
	"fmt"
	"net"
	"strings"
	"testing"

	"golang.design/x/hotkey"
)

func TestFunctionKey(t *testing.T) {
	tests := map[string]hotkey.Key{
		"F6":   hotkey.KeyF6,
		"f7":   hotkey.KeyF7,
		" F8 ": hotkey.KeyF8,
		"F9":   hotkey.KeyF9,
		"F10":  hotkey.KeyF10,
		"F11":  hotkey.KeyF11,
		"F12":  hotkey.KeyF12,
	}
	for input, expected := range tests {
		t.Run(input, func(t *testing.T) {
			actual, err := functionKey(input)
			if err != nil {
				t.Fatalf("functionKey(%q) returned %v", input, err)
			}
			if actual != expected {
				t.Fatalf("functionKey(%q) = %v, want %v", input, actual, expected)
			}
		})
	}

	if _, err := functionKey("ctrl+f9"); err == nil {
		t.Fatal("functionKey accepted a non-function-key chord")
	}
}

func TestValidateHotkeysRejectsCollision(t *testing.T) {
	if _, _, err := validateHotkeys("F9", "f9"); err == nil {
		t.Fatal("validateHotkeys accepted colliding keys")
	}

	dictate, read, err := validateHotkeys("F7", "F12")
	if err != nil {
		t.Fatalf("validateHotkeys returned %v", err)
	}
	if dictate != hotkey.KeyF7 || read != hotkey.KeyF12 {
		t.Fatalf("validateHotkeys returned %v and %v", dictate, read)
	}
}

func TestAuthenticateUsesCapability(t *testing.T) {
	client, server := net.Pipe()
	defer client.Close()
	defer server.Close()

	go func() {
		reader := bufio.NewReader(server)
		line, _ := reader.ReadString('\n')
		if line != "AUTH secret-token\n" {
			_, _ = fmt.Fprintln(server, "AUTH DENIED")
			return
		}
		_, _ = fmt.Fprintln(server, "AUTH OK")
	}()

	reader, err := authenticate(client, "secret-token")
	if err != nil {
		t.Fatalf("authenticate returned %v", err)
	}
	if reader == nil {
		t.Fatal("authenticate returned a nil reader")
	}
}

func TestAuthenticateRejectsDeniedPeer(t *testing.T) {
	client, server := net.Pipe()
	defer client.Close()
	defer server.Close()

	go func() {
		reader := bufio.NewReader(server)
		_, _ = reader.ReadString('\n')
		_, _ = fmt.Fprintln(server, "AUTH DENIED")
	}()

	_, err := authenticate(client, "wrong-token")
	if err == nil || !strings.Contains(err.Error(), "rejected") {
		t.Fatalf("authenticate error = %v, want rejected", err)
	}
}

func TestIntentionalShutdownIgnoresLateSendFailure(t *testing.T) {
	runtimeErrMu.Lock()
	runtimeErr = nil
	quitting.Store(false)
	runtimeErrMu.Unlock()

	beginShutdown()
	failTray(fmt.Errorf("late hotkey send"))

	if err := getRuntimeError(); err != nil {
		t.Fatalf("intentional shutdown recorded late error: %v", err)
	}

	runtimeErrMu.Lock()
	quitting.Store(false)
	runtimeErrMu.Unlock()
}
