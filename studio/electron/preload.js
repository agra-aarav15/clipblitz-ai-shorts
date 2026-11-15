'use strict';

// The studio is a normal web app. This bridge is deliberately tiny: it tells the
// page it is running inside the desktop shell (for copy and external-link handling)
// and exposes no Node APIs to the page.
const { contextBridge } = require('electron');

contextBridge.exposeInMainWorld('clipblitzDesktop', Object.freeze({
  platform: process.platform,
  electron: process.versions.electron,
}));
