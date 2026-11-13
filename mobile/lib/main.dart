import 'dart:io';

import 'package:flutter/material.dart';
import 'package:path_provider/path_provider.dart';

import 'app_state.dart';
import 'ui/home_page.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final docs = await getApplicationDocumentsDirectory();
  final app = AppState(Directory('${docs.path}/ai_mind')..createSync(recursive: true));
  await app.init();
  runApp(AiMindApp(app: app));
}

class AiMindApp extends StatelessWidget {
  const AiMindApp({super.key, required this.app});
  final AppState app;

  @override
  Widget build(BuildContext context) {
    const seed = Color(0xFF2F5D50);
    return MaterialApp(
      title: 'AI 录音思考',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(colorSchemeSeed: seed, useMaterial3: true),
      darkTheme: ThemeData(
          colorSchemeSeed: seed, brightness: Brightness.dark, useMaterial3: true),
      home: HomePage(app: app),
    );
  }
}
