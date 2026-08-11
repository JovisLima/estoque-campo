const { app, BrowserWindow } = require("electron");
const path = require("path");

function criarJanela() {
  const win = new BrowserWindow({
    width: 1200,
    height: 800,
    backgroundColor: "#0f172a",
    autoHideMenuBar: true,
    title: "Aven Connect - Estoque de Campo",
    icon: path.join(__dirname, "src", "assets", "logo.ico"),
    webPreferences: {
      contextIsolation: true,
    },
  });
  win.loadFile(path.join(__dirname, "src", "index.html"));
}

app.whenReady().then(() => {
  criarJanela();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) criarJanela();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
