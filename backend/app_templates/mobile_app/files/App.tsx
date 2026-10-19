import { useState } from "react";
import { Button, SafeAreaView, Text, TextInput, View } from "react-native";
import { backend, signIn, signOut } from "./src/api";

export default function App() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [me, setMe] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  async function login() {
    setError(null);
    try {
      await signIn(email, password);
      setMe(await backend("/api/me"));
    } catch (caught: any) {
      setError(caught.message);
    }
  }

  return (
    <SafeAreaView style={{ flex: 1, padding: 24, gap: 12 }}>
      <Text style={{ fontSize: 24, fontWeight: "600" }}>{{display_name}}</Text>
      {me ? (
        <View style={{ gap: 12 }}>
          <Text>Signed in as {me.email}</Text>
          <Button title="Sign out" onPress={() => signOut().then(() => setMe(null))} />
        </View>
      ) : (
        <View style={{ gap: 12 }}>
          <TextInput placeholder="E-mail" autoCapitalize="none" value={email} onChangeText={setEmail}
            style={{ borderWidth: 1, borderRadius: 6, padding: 8 }} />
          <TextInput placeholder="Password" secureTextEntry value={password} onChangeText={setPassword}
            style={{ borderWidth: 1, borderRadius: 6, padding: 8 }} />
          {error && <Text style={{ color: "red" }}>{error}</Text>}
          <Button title="Sign in" onPress={login} />
        </View>
      )}
    </SafeAreaView>
  );
}
