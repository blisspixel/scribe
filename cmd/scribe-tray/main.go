package main

import (
	"bufio"
	"flag"
	"fmt"
	"log"
	"net"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"fyne.io/systray"
	"golang.design/x/hotkey"
)

var (
	port          int
	dictateKey    string
	readKey       string
	iconPath      string
	dictateCode   hotkey.Key
	readCode      hotkey.Key
	iconData      []byte
	conn          net.Conn
	serviceReader *bufio.Reader
	writeMu       sync.Mutex
	runtimeErrMu  sync.Mutex
	runtimeErr    error
	registeredMu  sync.Mutex
	registered    []*hotkey.Hotkey
	quitting      atomic.Bool
)

func main() {
	if err := run(); err != nil {
		log.Printf("Scribe native tray stopped: %v", err)
		os.Exit(1)
	}
}

func run() error {
	flag.IntVar(&port, "port", 0, "Port for Python IPC server")
	flag.StringVar(&dictateKey, "dictate", "F9", "Hotkey for dictation")
	flag.StringVar(&readKey, "read", "F8", "Hotkey for read aloud")
	flag.StringVar(&iconPath, "icon", "", "Path to the canonical Scribe tray icon")
	flag.Parse()

	if port <= 0 {
		return fmt.Errorf("must provide a valid -port")
	}
	token := os.Getenv("SCRIBE_TRAY_IPC_TOKEN")
	if token == "" || strings.ContainsAny(token, "\r\n") {
		return fmt.Errorf("missing or invalid native tray IPC capability")
	}

	var err error
	dictateCode, readCode, err = validateHotkeys(dictateKey, readKey)
	if err != nil {
		return err
	}
	if iconPath == "" {
		return fmt.Errorf("must provide the canonical -icon path")
	}
	iconData, err = os.ReadFile(iconPath)
	if err != nil {
		return fmt.Errorf("read tray icon: %w", err)
	}

	conn, err = net.Dial("tcp", fmt.Sprintf("127.0.0.1:%d", port))
	if err != nil {
		return fmt.Errorf("connect to Python service: %w", err)
	}
	defer conn.Close()

	serviceReader, err = authenticate(conn, token)
	if err != nil {
		return err
	}

	systray.Run(onReady, onExit)
	return getRuntimeError()
}

func authenticate(connection net.Conn, token string) (*bufio.Reader, error) {
	if token == "" || strings.ContainsAny(token, "\r\n") {
		return nil, fmt.Errorf("invalid native tray IPC capability")
	}
	if err := connection.SetDeadline(time.Now().Add(5 * time.Second)); err != nil {
		return nil, fmt.Errorf("set authentication deadline: %w", err)
	}
	defer func() {
		_ = connection.SetDeadline(time.Time{})
	}()
	if _, err := fmt.Fprintf(connection, "AUTH %s\n", token); err != nil {
		return nil, fmt.Errorf("send native tray authentication: %w", err)
	}
	reader := bufio.NewReader(connection)
	response, err := reader.ReadString('\n')
	if err != nil {
		return nil, fmt.Errorf("read native tray authentication: %w", err)
	}
	if strings.TrimSpace(response) != "AUTH OK" {
		return nil, fmt.Errorf("native tray IPC authentication rejected")
	}
	return reader, nil
}

func monitorService(reader *bufio.Reader) {
	scanner := bufio.NewScanner(reader)
	for scanner.Scan() {
		message := scanner.Text()
		if strings.HasPrefix(message, "STATE:") {
			updateTrayState(strings.TrimPrefix(message, "STATE:"))
		}
	}
	if quitting.Load() {
		return
	}
	if err := scanner.Err(); err != nil {
		failTray(fmt.Errorf("Python service connection failed: %w", err))
		return
	}
	failTray(fmt.Errorf("Python service connection closed unexpectedly"))
}

func updateTrayState(state string) {
	switch state {
	case "idle":
		systray.SetTooltip("Scribe - Ready")
	case "recording":
		systray.SetTooltip("Scribe - Recording")
	case "transcribing":
		systray.SetTooltip("Scribe - Transcribing")
	case "speaking":
		systray.SetTooltip("Scribe - Reading Aloud")
	case "error":
		systray.SetTooltip("Scribe - Error")
	case "stopped":
		systray.SetTooltip("Scribe - Stopped")
	}
}

func onReady() {
	systray.SetTitle("Scribe")
	systray.SetTooltip("Scribe - Starting")
	systray.SetIcon(iconData)

	if err := setupHotkeys(); err != nil {
		failTray(err)
		return
	}

	mDictate := systray.AddMenuItem("Start/Stop Dictation ("+dictateKey+")", "Toggle dictation")
	mRead := systray.AddMenuItem("Read Selected Text ("+readKey+")", "Read out loud")
	systray.AddSeparator()
	mQuit := systray.AddMenuItem("Quit", "Quit Scribe")

	if err := sendCommand("READY"); err != nil {
		failTray(fmt.Errorf("confirm native tray readiness: %w", err))
		return
	}
	go monitorService(serviceReader)
	startHotkeyListeners()

	go func() {
		for {
			select {
			case <-mDictate.ClickedCh:
				if err := sendCommand("DICTATE"); err != nil {
					failTray(err)
					return
				}
			case <-mRead.ClickedCh:
				if err := sendCommand("READ"); err != nil {
					failTray(err)
					return
				}
			case <-mQuit.ClickedCh:
				beginShutdown()
				if err := sendCommand("QUIT"); err != nil {
					log.Printf("Could not notify Python service during quit: %v", err)
				}
				systray.Quit()
				return
			}
		}
	}()
}

func sendCommand(command string) error {
	writeMu.Lock()
	defer writeMu.Unlock()
	if conn == nil {
		return fmt.Errorf("native tray IPC connection is unavailable")
	}
	if _, err := fmt.Fprintf(conn, "%s\n", command); err != nil {
		return fmt.Errorf("send %s command: %w", strings.ToLower(command), err)
	}
	return nil
}

func functionKey(value string) (hotkey.Key, error) {
	keys := map[string]hotkey.Key{
		"F6":  hotkey.KeyF6,
		"F7":  hotkey.KeyF7,
		"F8":  hotkey.KeyF8,
		"F9":  hotkey.KeyF9,
		"F10": hotkey.KeyF10,
		"F11": hotkey.KeyF11,
		"F12": hotkey.KeyF12,
	}
	canonical := strings.ToUpper(strings.TrimSpace(value))
	key, ok := keys[canonical]
	if !ok {
		return 0, fmt.Errorf("native tray hotkey %q is unsupported; use F6 through F12", value)
	}
	return key, nil
}

func validateHotkeys(dictate string, read string) (hotkey.Key, hotkey.Key, error) {
	dictateResolved, err := functionKey(dictate)
	if err != nil {
		return 0, 0, fmt.Errorf("dictate hotkey: %w", err)
	}
	readResolved, err := functionKey(read)
	if err != nil {
		return 0, 0, fmt.Errorf("read hotkey: %w", err)
	}
	if dictateResolved == readResolved {
		return 0, 0, fmt.Errorf("dictate and read hotkeys must be different")
	}
	return dictateResolved, readResolved, nil
}

func setupHotkeys() error {
	dictateHotkey := hotkey.New([]hotkey.Modifier{}, dictateCode)
	if err := dictateHotkey.Register(); err != nil {
		return fmt.Errorf("register dictate hotkey %s: %w", dictateKey, err)
	}
	readHotkey := hotkey.New([]hotkey.Modifier{}, readCode)
	if err := readHotkey.Register(); err != nil {
		_ = dictateHotkey.Unregister()
		return fmt.Errorf("register read hotkey %s: %w", readKey, err)
	}
	registeredMu.Lock()
	registered = []*hotkey.Hotkey{dictateHotkey, readHotkey}
	registeredMu.Unlock()
	return nil
}

func startHotkeyListeners() {
	registeredMu.Lock()
	keys := append([]*hotkey.Hotkey(nil), registered...)
	registeredMu.Unlock()
	if len(keys) != 2 {
		failTray(fmt.Errorf("native hotkeys were not registered before readiness"))
		return
	}
	dictateHotkey, readHotkey := keys[0], keys[1]
	go func() {
		for range dictateHotkey.Keydown() {
			if err := sendCommand("DICTATE"); err != nil {
				failTray(err)
				return
			}
		}
	}()
	go func() {
		for range readHotkey.Keydown() {
			if err := sendCommand("READ"); err != nil {
				failTray(err)
				return
			}
		}
	}()
}

func failTray(err error) {
	runtimeErrMu.Lock()
	if quitting.Load() {
		runtimeErrMu.Unlock()
		return
	}
	if runtimeErr == nil {
		runtimeErr = err
	}
	runtimeErrMu.Unlock()
	systray.Quit()
}

func beginShutdown() bool {
	runtimeErrMu.Lock()
	alreadyQuitting := quitting.Swap(true)
	runtimeErrMu.Unlock()
	return alreadyQuitting
}

func getRuntimeError() error {
	runtimeErrMu.Lock()
	defer runtimeErrMu.Unlock()
	return runtimeErr
}

func onExit() {
	alreadyQuitting := beginShutdown()
	if !alreadyQuitting {
		if err := sendCommand("QUIT"); err != nil && getRuntimeError() == nil {
			log.Printf("Could not notify Python service during shutdown: %v", err)
		}
	}
	registeredMu.Lock()
	keys := registered
	registered = nil
	registeredMu.Unlock()
	for _, key := range keys {
		if err := key.Unregister(); err != nil {
			log.Printf("Could not unregister native hotkey: %v", err)
		}
	}
}
