import React from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { StatusBar } from 'expo-status-bar';
import { Text, View, ActivityIndicator } from 'react-native';
import { LoginScreen } from '@/screens/LoginScreen';
import { DriverScreen } from '@/screens/DriverScreen';
import { TripsScreen } from '@/screens/TripsScreen';
import { ProfileScreen } from '@/screens/ProfileScreen';
import { SettingsScreen } from '@/screens/SettingsScreen';
import { TripDetailScreen } from '@/screens/TripDetailScreen';
import { ChangePasswordScreen } from '@/screens/ChangePasswordScreen';
import { VehiclePickerScreen } from '@/screens/VehiclePickerScreen';
import { useAuthStore } from '@/store/authStore';
import { colors } from '@/theme/colors';
import type { Vehicle } from '@/api/ble';

export type RootStackParamList = {
  Login: undefined;
  Main: undefined;
  TripDetail: { tripId: string };
  ChangePassword: undefined;
  VehiclePicker: { onPick?: (v: Vehicle) => void };
};

export type TabParamList = {
  Conduite: undefined;
  Trajets: undefined;
  Profil: undefined;
  Reglages: undefined;
};

const Stack = createNativeStackNavigator<RootStackParamList>();
const Tab = createBottomTabNavigator<TabParamList>();

// Icône texte simple (évite une dépendance d'icônes ; lisible sur mobile).
function TabIcon({ symbol, color }: { symbol: string; color: string }) {
  return <Text style={{ fontSize: 18, color }}>{symbol}</Text>;
}

function MainTabs() {
  return (
    <Tab.Navigator
      screenOptions={{
        headerStyle: { backgroundColor: colors.bg },
        headerTintColor: colors.text,
        headerTitleStyle: { fontWeight: '600' },
        tabBarStyle: { backgroundColor: colors.bgCard, borderTopColor: colors.border },
        tabBarActiveTintColor: colors.primary,
        tabBarInactiveTintColor: colors.textMuted,
      }}
    >
      <Tab.Screen
        name="Conduite"
        component={DriverScreen}
        options={{
          title: 'Conduite',
          tabBarIcon: ({ color }) => <TabIcon symbol="🚚" color={color} />,
        }}
      />
      <Tab.Screen
        name="Trajets"
        component={TripsScreen}
        options={{
          title: 'Mes trajets',
          tabBarIcon: ({ color }) => <TabIcon symbol="🗺️" color={color} />,
        }}
      />
      <Tab.Screen
        name="Profil"
        component={ProfileScreen}
        options={{
          title: 'Profil',
          tabBarIcon: ({ color }) => <TabIcon symbol="👤" color={color} />,
        }}
      />
      <Tab.Screen
        name="Reglages"
        component={SettingsScreen}
        options={{
          title: 'Réglages',
          tabBarIcon: ({ color }) => <TabIcon symbol="⚙️" color={color} />,
        }}
      />
    </Tab.Navigator>
  );
}

export function RootNavigator() {
  const { user, loading, mustChangePassword } = useAuthStore();

  if (loading) {
    return (
      <View style={{ flex: 1, backgroundColor: colors.bg, justifyContent: 'center', alignItems: 'center' }}>
        <ActivityIndicator color={colors.primary} size="large" />
      </View>
    );
  }

  return (
    <NavigationContainer
      theme={{
        dark: true,
        colors: {
          primary: colors.primary,
          background: colors.bg,
          card: colors.bgCard,
          text: colors.text,
          border: colors.border,
          notification: colors.primary,
        },
      }}
    >
      <StatusBar style="light" />
      <Stack.Navigator
        screenOptions={{
          headerStyle: { backgroundColor: colors.bg },
          headerTintColor: colors.text,
          headerTitleStyle: { fontWeight: '600' },
          contentStyle: { backgroundColor: colors.bg },
        }}
      >
        {user ? (
          mustChangePassword ? (
            <Stack.Screen
              name="ChangePassword"
              component={ChangePasswordScreen}
              options={{ headerShown: false, gestureEnabled: false }}
            />
          ) : (
            <>
              <Stack.Screen name="Main" component={MainTabs} options={{ headerShown: false }} />
              <Stack.Screen
                name="TripDetail"
                component={TripDetailScreen}
                options={{ title: 'Détail du trajet' }}
              />
              <Stack.Screen
                name="ChangePassword"
                component={ChangePasswordScreen}
                options={{ title: 'Mot de passe' }}
              />
              <Stack.Screen
                name="VehiclePicker"
                component={VehiclePickerScreen}
                options={{ title: 'Choisir un véhicule' }}
              />
            </>
          )
        ) : (
          <Stack.Screen name="Login" component={LoginScreen} options={{ headerShown: false }} />
        )}
      </Stack.Navigator>
    </NavigationContainer>
  );
}
