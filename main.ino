#include <WiFi.h>
#include <DNSServer.h>
#include <WebServer.h>
#include <nvs_flash.h>

const char* ssid = "Graduation Greeting";

const byte DNS_PORT = 53;

// THE FIX: Use a fake "Public" IP instead of 192.168.4.1
// This tricks Android/Samsung/iOS into showing the popup immediately
IPAddress apIP(4, 3, 2, 1); 
DNSServer dnsServer;
WebServer server(80);

const char HTML_PAGE[] PROGMEM = R"=====([HTML_PAGE])=====";

void handleRoot() {
  server.sendHeader("Cache-Control", "no-cache, no-store, must-revalidate");
  server.sendHeader("Pragma", "no-cache");
  server.sendHeader("Expires", "-1");
  server.send(200, "text/html; charset=utf-8", HTML_PAGE);
}

void redirectToPortal() {
  server.sendHeader("Location", "http://4.3.2.1/", true);
  server.send(302, "text/plain", "");
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  
  nvs_flash_erase();
  nvs_flash_init();
  
  WiFi.disconnect(true);
  WiFi.mode(WIFI_AP);
  WiFi.setTxPower(WIFI_POWER_8_5dBm); 
  
  // 1. Start AP first, wait 100ms, THEN set the IP (fixes ESP32 IP bug)
  WiFi.softAP(ssid, NULL, 1, 0, 4);
  delay(100); 
  WiFi.softAPConfig(apIP, apIP, IPAddress(255, 255, 255, 0));
  
  // 2. Start DNS with TTL = 0 so phones don't cache it
  dnsServer.setTTL(0);
  dnsServer.setErrorReplyCode(DNSReplyCode::NoError);
  dnsServer.start(DNS_PORT, "*", apIP);
  
  // 3. Captive Portal Routes
  server.on("/", handleRoot);
  
  // Android & Chrome
  server.on("/generate_204", redirectToPortal);
  server.on("/gen_204", redirectToPortal);
  
  // Apple iOS / macOS
  server.on("/hotspot-detect.html", handleRoot);
  server.on("/library/test/success.html", handleRoot);
  
  // Windows
  server.on("/ncsi.txt", redirectToPortal);
  server.on("/connecttest.txt", redirectToPortal);
  server.on("/redirect", redirectToPortal);
  
  // Catch-all
  server.onNotFound(redirectToPortal);
  
  server.begin();
  Serial.println("Portal Ready at http://4.3.2.1");
}

void loop() {
  dnsServer.processNextRequest();
  server.handleClient();
}