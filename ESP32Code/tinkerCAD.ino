#include <Servo.h>

// Define servo pins for 8 servos
int servoPins[8] = {2, 3, 4, 5, 6, 7, 8, 9};
int servoPositions[8] = {0, 0, 0, 0, 0, 0, 0, 0};

// Support for multiple recordings (0-9)
int recordedPositions[10][8]; // 10 recordings, 8 servos each
bool hasRecording[10] = {false, false, false, false, false, false, false, false, false, false};

Servo servos[8];

// FUNCTION DECLARATIONS (Forward declarations)
void controlGroup(int groupNum);
void handleRecordCommand();
void handlePlayCommand();
void recordPosition(int slot);
void playRecordedPosition(int slot);
void resetAllPositions();
void displayCurrentPositions();
void displayRecordedPositions(int slot);

void setup() {
  Serial.begin(9600);
  
  for (int i = 0; i < 8; i++) {
    servos[i].attach(servoPins[i]);
    servos[i].write(servoPositions[i]);
  }
  
  // Initialize all recordings to 90°
  for (int i = 0; i < 10; i++) {
    for (int j = 0; j < 8; j++) {
      recordedPositions[i][j] = 90;
    }
  }
  
  Serial.println("8-Servo Control with Multi-Recording Ready");
  Serial.println("Commands: #X=record slot X, *X=play slot X, R=reset");
  Serial.println("Example: #1 record to slot 1, *1 play slot 1");
}

void loop() {
  Serial.println("Enter group (1-4) or command (#X/*X/R):");
  while (Serial.available() == 0) {}
  
  char firstChar = Serial.peek();
  
  if (firstChar == '#') {
    handleRecordCommand();
    return;
  }
  else if (firstChar == '*') {
    handlePlayCommand();
    return;
  }
  else if (firstChar == 'R' || firstChar == 'r') {
    Serial.read(); // Consume the 'R'
    while (Serial.available() > 0) { Serial.read(); }
    resetAllPositions();
    return;
  }
  
  // Normal group control
  int groupNum = Serial.parseInt();
  while (Serial.available() > 0) { Serial.read(); }
  
  if (groupNum >= 1 && groupNum <= 4) {
    controlGroup(groupNum);
  } else {
    Serial.println("Invalid input!");
  }
  delay(100);
}

void handleRecordCommand() {
  Serial.read(); // Consume the '#'
  
  if (Serial.available() == 0) {
    Serial.println("Specify slot number: #0 to #9");
    while (Serial.available() == 0) {}
  }
  
  int slot = Serial.parseInt();
  while (Serial.available() > 0) { Serial.read(); }
  
  if (slot >= 0 && slot <= 9) {
    recordPosition(slot);
  } else {
    Serial.println("Invalid slot! Use #0 to #9");
  }
}

void handlePlayCommand() {
  Serial.read(); // Consume the '*'
  
  if (Serial.available() == 0) {
    Serial.println("Specify slot number: *0 to *9");
    while (Serial.available() == 0) {}
  }
  
  int slot = Serial.parseInt();
  while (Serial.available() > 0) { Serial.read(); }
  
  if (slot >= 0 && slot <= 9) {
    playRecordedPosition(slot);
  } else {
    Serial.println("Invalid slot! Use *0 to *9");
  }
}

void controlGroup(int groupNum) {
  int leftServo = (groupNum - 1) * 2;
  int rightServo = leftServo + 1;
  
  bool inActionMode = true;
  while (inActionMode) {
    Serial.println("Enter: A,B,C,D or #/*/R/X?");
    while (Serial.available() == 0) {}
    
    char inputChar = Serial.read();
    while (Serial.available() > 0) { Serial.read(); }
    
    // Check for special commands
    if (inputChar == '#') {
      handleRecordCommand();
      continue; // Stay in action mode
    }
    else if (inputChar == '*') {
      handlePlayCommand();
      continue; // Stay in action mode
    }
    else if (inputChar == 'R' || inputChar == 'r') {
      resetAllPositions();
      continue; // Stay in action mode
    }
    else if (inputChar == 'X' || inputChar == 'x') {
      inActionMode = false;
      break;
    }
    
    // Normal action commands
    char commands[4] = {'A', 'B', 'C', 'D'};
    int leftChanges[4] = {+10, -10, +10, -10};
    int rightChanges[4] = {-10, +10, +10, -10};
    String actionNames[4] = {"Protract", "Retract", "Left", "Right"};
    
    bool actionFound = false;
    for (int i = 0; i < 4; i++) {
      if (inputChar == commands[i] || inputChar == commands[i] + 32) {
        // Execute the action
        servoPositions[leftServo] = constrain(servoPositions[leftServo] + leftChanges[i], 0, 180);
        servoPositions[rightServo] = constrain(servoPositions[rightServo] + rightChanges[i], 0, 180);
        servos[leftServo].write(servoPositions[leftServo]);
        servos[rightServo].write(servoPositions[rightServo]);
        
        Serial.print("Group "); Serial.print(groupNum);
        Serial.print(": "); Serial.println(actionNames[i]);
        displayCurrentPositions();
        actionFound = true;
        break;
      }
    }
    
    if (!actionFound) {
      Serial.println("Invalid action! Use A, B, C, D, #, *, R, or X");
    }
    
    delay(500);
  }
}

void recordPosition(int slot) {
  for (int i = 0; i < 8; i++) {
    recordedPositions[slot][i] = servoPositions[i];
  }
  hasRecording[slot] = true;
  
  Serial.print("=== POSITION RECORDED TO SLOT "); Serial.print(slot); Serial.println(" ===");
  displayRecordedPositions(slot);
}

void playRecordedPosition(int slot) {
  if (!hasRecording[slot]) {
    Serial.print("No recording in slot "); Serial.println(slot);
    return;
  }
  
  Serial.print("=== PLAYING SLOT "); Serial.print(slot); Serial.println(" ===");
  
  for (int i = 0; i < 8; i++) {
    servoPositions[i] = recordedPositions[slot][i];
    servos[i].write(servoPositions[i]);
    delay(100);
  }
  
  Serial.println("Playback complete!");
  displayCurrentPositions();
}

void resetAllPositions() {
  Serial.println("=== RESETTING ALL POSITIONS TO 90° ===");
  
  for (int i = 0; i < 8; i++) {
    servoPositions[i] = 90;
    servos[i].write(servoPositions[i]);
    delay(50);
  }
  
  Serial.println("All servos reset to 90°");
  displayCurrentPositions();
}

void displayCurrentPositions() {
  Serial.print("Current: ");
  for (int i = 0; i < 8; i++) {
    Serial.print("S"); Serial.print(i);
    Serial.print(":"); Serial.print(servoPositions[i]);
    if (i < 7) Serial.print(", ");
  }
  Serial.println();
}

void displayRecordedPositions(int slot) {
  Serial.print("Slot "); Serial.print(slot); Serial.print(": ");
  for (int i = 0; i < 8; i++) {
    Serial.print("S"); Serial.print(i);
    Serial.print(":"); Serial.print(recordedPositions[slot][i]);
    if (i < 7) Serial.print(", ");
  }
  Serial.println();
}