#include <WiFi.h>
#include <DNSServer.h>
#include <WebServer.h>
#include <nvs_flash.h>
#include "esp_netif.h"

const char* ssid = "Frequenza Silente";

const byte DNS_PORT = 53;

// THE FIX: Use a fake "Public" IP instead of 192.168.4.1
// This forces Android (Samsung/Xiaomi/Pixel) to trigger the captive portal popup immediately
IPAddress apIP(4, 3, 2, 1); 
DNSServer dnsServer;
WebServer server(80);

const char HTML_PAGE[] PROGMEM = R"=====([HTML_PAGE])=====";

void handleRoot() {
  server.sendHeader("Cache-Control", "no-cache, no-store, must-revalidate");
  server.sendHeader("Pragma", "no-cache");
  server.sendHeader("Expires", "-1");
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.send(200, "text/html; charset=utf-8", HTML_PAGE);
}

void redirectToPortal() {
  server.sendHeader("Location", "http://4.3.2.1/", true);
  server.send(302, "text/html", "<html><body><a href=\"http://4.3.2.1/\">Redirecting...</a></body></html>");
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

  // 1b. (Optional) RFC 8910 DHCP Option 114 is omitted because iOS strictly rejects http:// URIs for Option 114
  // Standard DNS redirection + HTTP 302 handles both Android and iOS reliably
  
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
  server.on("/hotspot-detect.html", redirectToPortal);
  server.on("/canonical.html", redirectToPortal);
  server.on("/success.txt", redirectToPortal);
  server.on("/library/test/success.html", redirectToPortal);
  
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