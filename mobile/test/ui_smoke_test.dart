// 界面冒烟测试：把四个标签页在手机尺寸下都画一遍（深色 / 浅色、连电脑 / 独立复盘），有布局溢出或异常就失败。
// 设了环境变量 UI_SHOTS=<文件夹> 时，顺便把每一页存成 PNG（本机看效果用；需要系统里有中文字体）。
import 'dart:convert';
import 'dart:io';
import 'dart:ui' as ui;

import 'package:ai_mind/app_state.dart';
import 'package:ai_mind/ui/shell.dart';
import 'package:ai_mind/ui/theme.dart';
import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

final _shots = Platform.environment['UI_SHOTS'] ?? '';

Future<void> _loadFonts() async {
  if (_shots.isEmpty) return;
  Future<void> load(String family, List<String> candidates) async {
    for (final path in candidates) {
      final f = File(path);
      if (!f.existsSync()) continue;
      final bytes = f.readAsBytesSync();
      await (FontLoader(family)..addFont(Future.value(ByteData.sublistView(bytes)))).load();
      return;
    }
  }

  final flutterRoot = Platform.environment['FLUTTER_ROOT'] ?? '';
  await load('MaterialIcons', ['$flutterRoot/bin/cache/artifacts/material_fonts/MaterialIcons-Regular.otf']);
  for (final family in ['Roboto', 'Segoe UI', '.SF UI Text', '.SF Pro Text']) {
    await load(family, [r'C:\Windows\Fonts\Deng.ttf', r'C:\Windows\Fonts\simhei.ttf', '/System/Library/Fonts/PingFang.ttc']);
  }
}

Map<String, dynamic> _sampleSession() => {
      'id': '20260101_090000',
      'date': '2026-01-01',
      'started': '2026-01-01T09:00:00',
      'title': '新产品定价',
      'status': 'done',
      'summary': '## 整体在聊什么\n今天主要在想新产品怎么定价。\n## 行动清单\n- [ ] 找三个老客户聊聊愿意付多少（高）\n- [ ] 算一下 **成本底线**（中）',
      'reviews': [
        {
          'id': 1, 'kind': 'periodic', 'status': 'done', 'date': '2026-01-01', 'from_clock': '09:00', 'to_clock': '09:10', 'sec': 312, 'chars': 86,
          'text': '[09:00:05] 我在想这个产品到底该卖多少钱，太便宜了怕别人觉得不值钱。',
          'analysis': {
            'title': '定价的犹豫',
            'summary': '你反复在“卖便宜走量”和“卖贵做口碑”之间摇摆，还没有拿客户的真实反应来验证。',
            'blind_spots': ['你只从自己的成本出发，没有问过客户觉得值多少', '没考虑续费，只在想第一次成交'],
            'latent_needs': [{'need': '想要一个不用反复纠结的定价依据', 'evidence': '“我老是拿不定主意”'}],
            'divergent': [{'angle': '反向思考', 'idea': '如果免费，靠什么赚钱？'}, {'angle': '跨行业', 'idea': '健身房的年卡定价'}],
            'suggestions': [{'text': '本周约三个老客户各聊 15 分钟', 'priority': '高'}, {'text': '列出三档价格做对比', 'priority': '中'}],
            'questions': ['如果只能留一个卖点，是哪个？'],
            'voice_cues': ['说到“太便宜”时语速明显变快，有点着急'],
          },
        },
        {'id': 2, 'kind': 'periodic', 'status': 'analyzing', 'date': '2026-01-01', 'from_clock': '09:10', 'to_clock': '09:20', 'sec': 140, 'chars': 0, 'text': ''},
        {'id': 3, 'kind': 'manual', 'status': 'error', 'error': 'AI 接口返回 HTTP 500：boom', 'date': '2026-01-01', 'from_clock': '09:20', 'to_clock': '09:25', 'sec': 60, 'chars': 0, 'text': ''},
      ],
      'paragraphs': [
        {'id': 1, 'start_clock': '09:00:05', 'sec': 40, 'text': '我在想这个产品到底该卖多少钱，太便宜了怕别人觉得不值钱。', 'status': 'done'},
        {'id': 2, 'start_clock': '09:12:30', 'sec': 30, 'text': '', 'status': 'pending'},
      ],
      'last_review_ms': 0,
    };

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  for (final dark in [true, false]) {
    for (final standalone in [true, false]) {
      testWidgets('四个标签页都能正常显示（${dark ? '深色' : '浅色'}，${standalone ? '独立复盘' : '连电脑'}）', (tester) async {
        // 没有真正的麦克风 / 网络插件：让插件调用都返回空
        for (final ch in ['com.llfbandit.record/messages', 'ai_mind/android', 'dev.fluttercommunity.plus/connectivity', 'plugins.flutter.io/path_provider']) {
          tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(MethodChannel(ch), (_) async => null);
        }
        await tester.runAsync(_loadFonts);
        tester.view.physicalSize = const Size(390 * 3, 844 * 3);
        tester.view.devicePixelRatio = 3;
        addTearDown(tester.view.reset);

        final dir = Directory.systemTemp.createTempSync('ui_smoke');
        File('${dir.path}/settings.json').writeAsStringSync(jsonEncode({
          'standalone': standalone,
          'splash': false,
          'autoCheckUpdate': false,
          'aiKey': standalone ? 'sk-test' : '',
          'deviceId': 'mtest0001',
        }));
        if (standalone) {
          Directory('${dir.path}/local/sessions').createSync(recursive: true);
          File('${dir.path}/local/sessions/20260101_090000.json').writeAsStringSync(jsonEncode(_sampleSession()));
        }
        final app = AppState(dir);
        if (standalone) await app.refresh();
        final key = GlobalKey();
        await tester.pumpWidget(RepaintBoundary(
          key: key,
          child: MaterialApp(
            debugShowCheckedModeBanner: false,
            theme: buildTheme(dark ? Brightness.dark : Brightness.light),
            home: Shell(app: app),
          ),
        ));

        Future<void> shot(String name) async {
          await tester.pump(); // 读数据的结果回来
          await tester.pump(); // 这一帧开始放动画
          await tester.pump(const Duration(milliseconds: 700)); // 等动画放完
          expect(tester.takeException(), isNull);
          if (_shots.isEmpty) return;
          await tester.runAsync(() async {
            final boundary = key.currentContext!.findRenderObject()! as RenderRepaintBoundary;
            final img = await boundary.toImage(pixelRatio: 2);
            final png = await img.toByteData(format: ui.ImageByteFormat.png);
            File('$_shots/${dark ? 'dark' : 'light'}-${standalone ? 'solo' : 'pc'}-$name.png')
              ..createSync(recursive: true)
              ..writeAsBytesSync(png!.buffer.asUint8List());
          });
        }

        await shot('1-home');
        if (standalone) {
          await tester.drag(find.byType(CustomScrollView), const Offset(0, -420));
          await shot('1b-home-reviews');
          await tester.tap(find.text('听写')); // 分段选择钉在顶上，翻下来也点得到
          await shot('1c-home-transcript');
        }
        for (final (name, label) in [('2-reports', '报告'), ('3-history', '历史'), ('4-settings', '设置')]) {
          await tester.tap(find.text(label).last);
          await shot(name);
        }
        await tester.drag(find.byType(ListView).last, const Offset(0, -900));
        await shot('4b-settings-more');

        await tester.pumpWidget(const SizedBox());
        app.dispose();
        await tester.pump(const Duration(seconds: 1));
      });
    }
  }
}
