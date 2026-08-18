import AsyncStorage from '@react-native-async-storage/async-storage';

const TOKEN_KEY = 'logitrak.jwt';
const USER_KEY = 'logitrak.user';

export async function saveToken(token) {
  try { await AsyncStorage.setItem(TOKEN_KEY, token); } catch (e) {}
}
export async function getToken() {
  try { return await AsyncStorage.getItem(TOKEN_KEY); } catch (e) { return null; }
}
export async function saveUser(user) {
  try { await AsyncStorage.setItem(USER_KEY, JSON.stringify(user || null)); } catch (e) {}
}
export async function getUser() {
  try {
    const raw = await AsyncStorage.getItem(USER_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (e) { return null; }
}
export async function clearAuth() {
  try { await AsyncStorage.multiRemove([TOKEN_KEY, USER_KEY]); } catch (e) {}
}
