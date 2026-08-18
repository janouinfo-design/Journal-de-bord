const { getDefaultConfig } = require('expo/metro-config');
const path = require('path');

const config = getDefaultConfig(__dirname);

// Environnement conteneurisé : limites inotify basses (ENOSPC).
// On restreint les dossiers surveillés pour éviter la surcharge du watcher.
config.watchFolders = [path.resolve(__dirname)];
config.resolver = config.resolver || {};
config.resolver.blockList = [
  /node_modules\/react-native\/ReactAndroid\/.*/,
  /node_modules\/react-native\/React\/.*/,
  /node_modules\/react-native\/ReactCommon\/.*/,
  /node_modules\/.*\/android\/.*/,
  /node_modules\/.*\/ios\/.*/,
  /\.git\/.*/,
];

module.exports = config;
