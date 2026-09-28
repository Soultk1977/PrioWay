#include <SPI.h>
#include <LoRa.h>
#include "DFRobotDFPlayerMini.h"

// --- UART BRIDGE TO RASPBERRY PI ---
#define RXD2 16
#define TXD2 17

// --- LORA RADIO ---
#define LORA_SCK 18
#define LORA_MISO 19
#define LORA_MOSI 23
#define LORA_CS 5
#define LORA_DIO0 26

// --- TRAFFIC RELAYS (Active-LOW) ---
#define RELAY_RED 21
#define RELAY_YELLOW 22
#define RELAY_GREEN 25

// --- DFPLAYER MINI ---
#define DF_RX_PIN 4
#define DF_TX_PIN 13
#define DF_BUSY 14

// --- SENSORS ---
#define GAS_SENSOR 34

HardwareSerial DFSerial(1);
DFRobotDFPlayerMini myDFPlayer;

// --- STATE MACHINE VARIABLES ---
unsigned long lastLightChange = 0;
const long normalInterval = 5000; // 5 seconds per light

int currentLight = 0; // 0=Red, 1=Green, 2=Yellow
enum SystemState { NORMAL, PENDING_EMERGENCY, EMERGENCY_ACTIVE, PENDING_RESET };
SystemState state = NORMAL;

unsigned long transitionStartTime = 0;
const long transitionDelay = 5000; // 5 seconds for corridor transitions

bool loraOnline = false;
bool audioOnline = false;

void setPhysicalLights(int lightMode) {
  // Active-LOW Logic
  digitalWrite(RELAY_RED, lightMode == 0 ? LOW : HIGH);
  digitalWrite(RELAY_GREEN, lightMode == 1 ? LOW : HIGH);
  digitalWrite(RELAY_YELLOW, lightMode == 2 ? LOW : HIGH);
}

void setup() {
  Serial.begin(115200);
  delay(1000); // Give serial monitor time to catch boot logs
  Serial2.begin(115200, SERIAL_8N1, RXD2, TXD2);

  pinMode(RELAY_RED, OUTPUT);
  pinMode(RELAY_YELLOW, OUTPUT);
  pinMode(RELAY_GREEN, OUTPUT);
  pinMode(DF_BUSY, INPUT);
  
  setPhysicalLights(0); // Start on Red

  // Initialize LoRa
  SPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_CS);
  LoRa.setPins(LORA_CS, -1, LORA_DIO0);
  if (!LoRa.begin(433E6)) {
    Serial.println("WARNING: LoRa Failed!");
    loraOnline = false;
  } else {
    loraOnline = true;
  }

  // Initialize DFPlayer
  DFSerial.begin(9600, SERIAL_8N1, DF_RX_PIN, DF_TX_PIN);
  if (myDFPlayer.begin(DFSerial, false, false)) {
    myDFPlayer.volume(25);
    audioOnline = true;
  } else {
    audioOnline = false;
  }
  
  Serial.println("TRAFFIC_ESP32_READY");
}

void loop() {
  unsigned long currentMillis = millis();

  // --- 1. TRAFFIC LIGHT STATE MACHINE ---
  if (state == NORMAL || state == PENDING_EMERGENCY || state == PENDING_RESET) {
    if (currentMillis - lastLightChange >= normalInterval) {
      lastLightChange = currentMillis;
      
      if (currentLight == 0) currentLight = 1;
      else if (currentLight == 1) currentLight = 2;
      else if (currentLight == 2) currentLight = 0;
      
      setPhysicalLights(currentLight);
      
      Serial2.print("SYNC:LIGHT:");
      Serial2.println(currentLight);
    }
  }

  // --- 2. EMERGENCY TRANSITION LOGIC ---
  if (state == PENDING_EMERGENCY) {
    if (currentMillis - transitionStartTime >= transitionDelay) {
      state = EMERGENCY_ACTIVE;
      currentLight = 1; // Force Green
      setPhysicalLights(currentLight);
      
      if (audioOnline) myDFPlayer.play(1); 
      
      if (loraOnline) {
        LoRa.beginPacket();
        LoRa.print("RES:APPROVED");
        LoRa.endPacket();
      }
      
      Serial2.println("SYNC:CORRIDOR:ACTIVE");
    }
  } 
  else if (state == PENDING_RESET) {
    if (currentMillis - transitionStartTime >= transitionDelay) {
      state = NORMAL;
      currentLight = 0; // Force Red
      setPhysicalLights(currentLight);
      lastLightChange = currentMillis;
      
      Serial2.println("SYNC:CORRIDOR:CLEARED");
    }
  }

  // --- 3. LORA RECEIVE ---
  if (loraOnline) {
    int packetSize = LoRa.parsePacket();
    if (packetSize) {
      String incoming = "";
      while (LoRa.available()) {
        incoming += (char)LoRa.read();
      }
      Serial2.println(incoming); 
    }
  }

  // --- 4. RASPBERRY PI COMMANDS ---
  if (Serial2.available()) {
    String command = Serial2.readStringUntil('\n');
    command.trim();

    if (command == "CMD:APPROVE" && state == NORMAL) {
      state = PENDING_EMERGENCY;
      transitionStartTime = currentMillis;
      if (audioOnline) myDFPlayer.play(3); 
      Serial2.println("SYNC:CORRIDOR:PENDING");
    } 
    // FIX: Allow reset from PENDING or ACTIVE so it never gets stuck
    else if (command == "CMD:RESET" && (state == EMERGENCY_ACTIVE || state == PENDING_EMERGENCY)) {
      state = PENDING_RESET;
      transitionStartTime = currentMillis;
      if (audioOnline) myDFPlayer.play(2);
      Serial2.println("SYNC:RESET:PENDING");
    }
    else if (command == "CMD:SENSOR") {
      int gasVal = analogRead(GAS_SENSOR);
      Serial2.print("DATA:GAS:");
      Serial2.println(gasVal);
    }
  }
}