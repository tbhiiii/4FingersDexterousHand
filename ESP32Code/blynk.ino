#define BLYNK_TEMPLATE_ID "REDACTED_TEMPLATE_ID"
#define BLYNK_TEMPLATE_NAME "SERVO MOTOR WITH ESP 32"
#define BLYNK_AUTH_TOKEN "REDACTED_BLYNK_TOKEN"

#include <ESP32Servo.h>
#include <WiFi.h>
#include <WiFiClient.h>
#include <BlynkSimpleEsp32.h>

// You should get Auth Token in the Blynk App.
// Go to the Project Settings (nut icon).
char auth[] = "REDACTED_BLYNK_TOKEN";

// Your WiFi credentials.
// Set password to "" for open networks.
char ssid[] = "REDACTED_SSID";
char pass[] = "REDACTED_WIFI_PASS";

Servo servo[8];

int finger = 0;
int slot = 0;
int currentPosition[8];
int recordPosition[10][8];
int interval = 10;
int servoPin[8] = {12, 13, 32, 33, 25, 26, 27, 14};
int modeSelection;
int modeAngle;
int leftOrRight = 0;

bool isRecorded[10];
bool protractButton = 0;
bool retractButton = 0;
bool leftButton = 0;
bool rightButton = 0;
bool recordButton = 0;
bool replayButton = 0;
bool exitButton = 0;
bool resetButton = 0;
bool angleChanging = 0;
bool confirmSlot = 0;
bool hasRecord = 0;
bool modeHasSelected = 0;

void originalPosition();
void replay(int slot);
void record(int slot);
void exitProgram();
void turnOffButton();
void angleLimit(int angle1, int angle2);
void move(int a, int b);
void writeAngle();

BLYNK_WRITE(V0){ protractButton = param.asInt(); if(param.asInt() != 0){ turnOffButton();}} // Protract
BLYNK_WRITE(V1){ retractButton = param.asInt(); if(param.asInt() != 0){ turnOffButton();}} // Retract
BLYNK_WRITE(V2){ leftButton = param.asInt(); if(param.asInt() != 0){ turnOffButton();}} // Left
BLYNK_WRITE(V3){ rightButton = param.asInt(); if(param.asInt() != 0){ turnOffButton();}} // Right
BLYNK_WRITE(V4){ exitButton = param.asInt(); if(param.asInt() != 0){ turnOffButton();}} // Exit
BLYNK_WRITE(V5){ resetButton = param.asInt(); if(param.asInt() != 0){ turnOffButton();}} // Reset
BLYNK_WRITE(V6){ replayButton = param.asInt(); if(param.asInt() != 0){ Blynk.virtualWrite(V7, 0); recordButton = 0;}} // Replay_switch
BLYNK_WRITE(V7){ recordButton = param.asInt(); if(param.asInt() != 0){ Blynk.virtualWrite(V6, 0); replayButton = 0;}} // Record_switch
BLYNK_WRITE(V8){ finger = param.asInt(); if(param.asInt() != 0){ turnOffButton();}} // Finger select menu
//BLYNK_WRITE(V9){ joystick_x = param.asInt(); if(param.asInt() != 0){ turnOffButton();}} // joystick for x axis
BLYNK_WRITE(V10){ finger = param.asInt(); if(param.asInt() != 0){ turnOffButton();}} // Finger select slider
//BLYNK_WRITE(V11){ joystick_y = param.asInt(); if(param.asInt() != 0){ turnOffButton();}} // joystick for y axis
BLYNK_WRITE(V13){ slot = param.asInt(); } // Slot select
BLYNK_WRITE(V14){ confirmSlot = param.asInt();} // Confirm slot
BLYNK_WRITE(V16){ modeSelection = param.asInt();}

void setup() {
  Blynk.begin(auth, ssid, pass);
  Serial.begin(9600);
  for (int j=0; j<8; j++){ //8 servo
    servo[j].attach(servoPin[j], 544, 2400);  //configure which pins are used 
  }
/*  for (int i = 0; i < 10; i++){
    isrecorded[i] = false;
  }*/
  Blynk.virtualWrite(V17, "Terminal");
  originalPosition();
}

void loop() {
  Blynk.run();
  switch (modeSelection){
    case 2:
    Serial.println("Pls select the button");
    while(modeSelection == 1){};
    break;
    case 1:         //place
    modeAngle = -5;
    break;
    case 0:         //grip
    modeAngle = 5;
    break;
    case -1:        //demo
    modeAngle = 0;
    break;
  }

  if (recordButton){     //record button is pushed
    if (slot == 0 || confirmSlot == 0) {//wait if user haven't selected any slot
    return;
    }
    record(slot);
    Serial.println("returned");
  }else if(replayButton){
    if (slot == 0 || confirmSlot == 0) {//wait if user haven't selected any slot
    return;
    }
    replay(slot);
    Serial.println("returned");
  }else if(resetButton){
    Serial.println("Reset is executed");
    if (finger != 0){
      currentPosition[finger - 1] = 20;
      currentPosition[finger + 3] = 160;
      writeAngle();
    }else{
      Serial.println("No finger is selected");
    }
    Serial.println("returned");
    delay(100);
  }else if(exitButton){
    exitProgram();
    Serial.println("returned");
    delay(100);
  }

  if (finger != 0){
    if(protractButton){    //+-
      Serial.println("protract is executed");
      Blynk.virtualWrite(V17, "[Finger " + String(finger) + "] protract is executed\n");
      move(interval, -interval);
      Serial.println("returned");
    }else if(retractButton){ //-+
      Serial.println("retract is executed");
      Blynk.virtualWrite(V17, "[Finger " + String(finger) + "] retract is executed\n");
      move(-interval, +interval);
      Serial.println("returned");
    }else if(leftButton){ //++
      Serial.println("left is executed");
      Blynk.virtualWrite(V17, "[Finger " + String(finger) + "] left is executed\n");
      leftOrRight++;
      if(leftOrRight > 2){
        Serial.println("left limited");
        Blynk.virtualWrite(V17, "[Finger " + String(finger) + "] left is limited\n");
        delay(1000);
      }else{
        move(interval, interval);
        Serial.println("returned");
      }
    }else if(rightButton){ //--
      Serial.println("right is executed");
      Blynk.virtualWrite(V17, "[Finger " + String(finger) + "] right is limited\n");
      leftOrRight--;
      if(leftOrRight < -2){
        Serial.println("right limited");
        Blynk.virtualWrite(V17, "[Finger " + String(finger) + "] left is executed\n");
        delay(1000);
      }else{
        move(-interval, -interval);
        Serial.println("returned");
      }
    }
  }
}

void writeAngle(){
  for (int i = 0; i < 8; i++){
    servo[i].write(currentPosition[i]);      //rotate servo motor
    Serial.println(currentPosition[i]);
    Blynk.virtualWrite(V17, "Angle" + String(i+1) + ": " + String(currentPosition[i]) + "\n");
  }
}

void originalPosition(){
Serial.println("originalPosition is executed");
Blynk.virtualWrite(V17, "originalPosition is executed\n");
for (int j=0; j<4; j++){ //just easier for angle setting
  currentPosition[j] = 20;    //all the left servo become 0
  currentPosition[j+4] = 160;  //all the right servo become 180
}
writeAngle();         //synchronize to servo motors
return;
}

void move(int a, int b){
  Serial.println(finger);
  currentPosition[finger - 1] = currentPosition[finger - 1] + a;
  currentPosition[finger + 3] = currentPosition[finger + 3] + b;
  angleLimit(a, b);
  delay(1000);
  return;
}

void replay(int slot){
  Serial.println("replay is executed");
  Blynk.virtualWrite(V17, "replay is executed\n");
  if (isRecorded[slot - 1]){     //make sure slot have recorded
    for (int i = 0; i < 4; i++){
      servo[i].write(recordPosition[slot-1][i] + modeAngle);    //minus 1 because the input 1 will be slot[0]
      servo[i+4].write(recordPosition[slot-1][i+4] - modeAngle); 
      currentPosition[i] = recordPosition[slot-1][i] + modeAngle;
      currentPosition[i+4] = recordPosition[slot-1][i+4] - modeAngle;
      Serial.println(recordPosition[slot-1][i] + modeAngle);
      Serial.println(recordPosition[slot-1][i+4] - modeAngle);
    }
    for (int i = 0; i < 8; i++){
    //servo[i].write(currentPosition[i]);      //rotate servo motor
    //Serial.println(currentPosition[i]);
    Blynk.virtualWrite(V17, "Angle" + String(i+1) + ": " + String(currentPosition[i]) + "\n");
  } 
  }
  else{
    Serial.println("Slot is not recorded");
    Blynk.virtualWrite(V17, "Slot is not recorded\n");

  }
  turnOffButton();
  return;
}


void record(int slot){
  Serial.println("record is executed");
  Blynk.virtualWrite(V17, "record is executed\n");
  Serial.print("slot ");Serial.print(slot);Serial.println(" is selected");
  Blynk.virtualWrite(V17, "slot " + String(slot) + " is selected\n");
  for (int i = 0; i < 8; i++){
    recordPosition[slot-1][i] = currentPosition[i];   //record current position in slot-1
    Serial.println(recordPosition[slot - 1][i]);
    Blynk.virtualWrite(V17, "Angle" + String(i+1) + ": " + String(recordPosition[slot-1][i]) + "\n");
  }
  isRecorded[slot-1] = true;
  turnOffButton();
  return;
}

void exitProgram(){
  Serial.println("exitProgram is executed");
  Blynk.virtualWrite(V17, "exitProgram is executed\n");
  finger = 0;         //no finger is not chosen so the up/down/left/right and joystick are unabled
  originalPosition();
  return;
}

void turnOffButton(){
  Blynk.virtualWrite(V6, 0);
  Blynk.virtualWrite(V7, 0);
  recordButton = 0;
  replayButton = 0;
  return;
}

void angleLimit(int angle1, int angle2){
  if (currentPosition[finger - 1] >= 0 && currentPosition[finger - 1] <= 180 && currentPosition[finger + 3] >= 0 && currentPosition[finger + 3] <= 180){
  writeAngle();
  }else{
  currentPosition[finger - 1] = currentPosition[finger - 1] - angle1;
  currentPosition[finger + 3] = currentPosition[finger + 3] - angle2;
  }
  return;
}
