#include <SPI.h>
#include <LoRa.h>

// --- HARDWARE PIN DEFINITIONS ---
#define RXD2 16
#define TXD2 17

#define LORA_SCK 18
#define LORA_MISO 19
#define LORA_MOSI 23
#define LORA_CS 5
#define LORA_RST -1  // Not wired physically
#define LORA_DIO0 26

#define LED_RED 25
#define LED_GREEN 33
#define LED_BLUE 32

#define BTN_EMERGENCY 27
#define BTN_CANCEL 12
#define BUZZER_PIN 13

bool emergencyActive = false;

void setup() {
  Serial.begin(115200);
  Serial2.begin(9600, SERIAL_8N1, RXD2, TXD2); // GPS UART bridge

  pinMode(LED_RED, OUTPUT);
  pinMode(LED_GREEN, OUTPUT);
  pinMode(LED_BLUE, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  
  // Use internal pull-ups since the buttons connect to GND
  pinMode(BTN_EMERGENCY, INPUT_PULLUP);
  pinMode(BTN_CANCEL, INPUT_PULLUP);

  // Initialize LoRa
  SPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_CS);
  LoRa.setPins(LORA_CS, LORA_RST, LORA_DIO0);
  
  if (!LoRa.begin(433E6)) { // Ensure this matches your region's LoRa frequency (e.g., 433E6, 868E6, or 915E6)
    Serial.println("LoRa Initialization Failed!");
    while (1); // Halt execution if radio fails
  }
  
  digitalWrite(LED_BLUE, HIGH); // System Ready
  Serial.println("Vehicle Node Ready.");
}

void triggerBuzzer(int mode) {
  if (mode == 1) { // Single quick buzz for button press
    digitalWrite(BUZZER_PIN, HIGH);
    delay(100);
    digitalWrite(BUZZER_PIN, LOW);
  } else if (mode == 2) { // Double quick buzz for green corridor approval
    digitalWrite(BUZZER_PIN, HIGH);
    delay(100);
    digitalWrite(BUZZER_PIN, LOW);
    delay(100);
    digitalWrite(BUZZER_PIN, HIGH);
    delay(100);
    digitalWrite(BUZZER_PIN, LOW);
  }
}

void loop() {
  // --- 1. HANDLE USER INPUT ---
  if (digitalRead(BTN_EMERGENCY) == LOW) {
    if (!emergencyActive) {
      emergencyActive = true;
      triggerBuzzer(1);
      digitalWrite(LED_RED, HIGH);
      digitalWrite(LED_GREEN, LOW);
      
      LoRa.beginPacket();
      LoRa.print("REQ:EMERGENCY");
      LoRa.endPacket();
      Serial.println("Sent: EMERGENCY REQUEST");
    }
    delay(300); // Button debounce
  }

  if (digitalRead(BTN_CANCEL) == LOW) {
    if (emergencyActive) {
      emergencyActive = false;
      triggerBuzzer(1);
      digitalWrite(LED_RED, LOW);
      digitalWrite(LED_GREEN, LOW);
      
      LoRa.beginPacket();
      LoRa.print("REQ:CANCEL");
      LoRa.endPacket();
      Serial.println("Sent: CANCEL REQUEST");
    }
    delay(300); // Button debounce
  }

  // --- 2. LISTEN FOR TRAFFIC NODE APPROVAL ---
  int packetSize = LoRa.parsePacket();
  if (packetSize) {
    String incoming = "";
    while (LoRa.available()) {
      incoming += (char)LoRa.read();
    }
    
    if (incoming == "RES:APPROVED" && emergencyActive) {
      digitalWrite(LED_GREEN, HIGH);
      digitalWrite(LED_RED, LOW);
      triggerBuzzer(2);
      Serial.println("Received: CORRIDOR APPROVED");
    }
  }

  // --- 3. STREAM GPS DATA ---
  if (emergencyActive && Serial2.available() > 0) {
    String gpsData = Serial2.readStringUntil('\n');
    
    // Only transmit valid NMEA sentences to save radio bandwidth
    if (gpsData.startsWith("$GPGGA") || gpsData.startsWith("$GPRMC")) {
      LoRa.beginPacket();
      LoRa.print("GPS:");
      LoRa.print(gpsData);
      LoRa.endPacket();
    }
  }
}