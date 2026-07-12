//go:build windows

package main

import (
	"bufio"
	"flag"
	"fmt"
	"log"
	"net"
	"os"

	"fyne.io/systray"
	"golang.design/x/hotkey"
)

var (
	port        int
	dictateKey  string
	readKey     string
	conn        net.Conn
)

func main() {
	flag.IntVar(&port, "port", 0, "Port for Python IPC server")
	flag.StringVar(&dictateKey, "dictate", "F9", "Hotkey for dictation")
	flag.StringVar(&readKey, "read", "F8", "Hotkey for read aloud")
	flag.Parse()

	if port == 0 {
		log.Fatal("Must provide -port")
	}

	var err error
	conn, err = net.Dial("tcp", fmt.Sprintf("127.0.0.1:%d", port))
	if err != nil {
		log.Fatalf("Failed to connect to Python server: %v", err)
	}
	defer conn.Close()

	// Handle incoming messages from Python (like state updates)
	go func() {
		scanner := bufio.NewScanner(conn)
		for scanner.Scan() {
			msg := scanner.Text()
			// Basic state sync to update icon/tooltip if needed.
			// Format e.g., "STATE:listening" or "STATE:idle"
			if len(msg) > 6 && msg[:6] == "STATE:" {
				state := msg[6:]
				updateTrayState(state)
			}
		}
		// If Python dies, we die
		os.Exit(0)
	}()

	// Start systray
	systray.Run(onReady, onExit)
}

func updateTrayState(state string) {
	switch state {
	case "idle":
		systray.SetTooltip("Scribe - Ready")
		// Could update icon here if we had multiple byte slices
	case "listening":
		systray.SetTooltip("Scribe - Listening...")
	case "processing":
		systray.SetTooltip("Scribe - Transcribing...")
	case "reading":
		systray.SetTooltip("Scribe - Reading Aloud...")
	case "error":
		systray.SetTooltip("Scribe - Error")
	}
}

func onReady() {
	systray.SetTitle("Scribe")
	systray.SetTooltip("Scribe (Go Tray)")
	
	// A simple colored icon placeholder (or we can load bytes)
	// For now just use a simple 1x1 transparent pixel so it doesn't crash
	systray.SetIcon([]byte{
		0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00, 0x0d,
		0x49, 0x48, 0x44, 0x52, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
		0x08, 0x06, 0x00, 0x00, 0x00, 0x1f, 0x15, 0xc4, 0x89, 0x00, 0x00, 0x00,
		0x0b, 0x49, 0x44, 0x41, 0x54, 0x08, 0xd7, 0x63, 0x60, 0x00, 0x02, 0x00,
		0x00, 0x05, 0x00, 0x01, 0xe2, 0x26, 0x05, 0x9b, 0x00, 0x00, 0x00, 0x00,
		0x49, 0x45, 0x4e, 0x44, 0xae, 0x42, 0x60, 0x82,
	})

	mDictate := systray.AddMenuItem("Start/Stop Dictation ("+dictateKey+")", "Toggle dictation")
	mRead := systray.AddMenuItem("Read Selected Text ("+readKey+")", "Read out loud")
	systray.AddSeparator()
	mQuit := systray.AddMenuItem("Quit", "Quit Scribe")

	go func() {
		for {
			select {
			case <-mDictate.ClickedCh:
				sendCommand("DICTATE")
			case <-mRead.ClickedCh:
				sendCommand("READ")
			case <-mQuit.ClickedCh:
				sendCommand("QUIT")
				systray.Quit()
			}
		}
	}()

	// Setup Hotkeys
	setupHotkeys()
}

func sendCommand(cmd string) {
	if conn != nil {
		fmt.Fprintf(conn, "%s\n", cmd)
	}
}

func setupHotkeys() {
	go func() {
		// Currently golang.design/x/hotkey requires modifiers + key
		// To match Python's global keyboard hook, we map strings like "F9" to hotkey.KeyF9
		
		dKey := hotkey.New([]hotkey.Modifier{}, hotkey.KeyF9)
		if err := dKey.Register(); err == nil {
			go func() {
				for {
					<-dKey.Keydown()
					sendCommand("DICTATE")
				}
			}()
		} else {
			log.Printf("Failed to register dictate hotkey: %v", err)
		}

		rKey := hotkey.New([]hotkey.Modifier{}, hotkey.KeyF8)
		if err := rKey.Register(); err == nil {
			go func() {
				for {
					<-rKey.Keydown()
					sendCommand("READ")
				}
			}()
		} else {
			log.Printf("Failed to register read hotkey: %v", err)
		}
	}()
}

func onExit() {
	// Cleanup
}
