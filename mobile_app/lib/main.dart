import 'dart:io';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:geolocator/geolocator.dart';
import 'package:image_picker/image_picker.dart';
import 'package:share_plus/share_plus.dart';
import 'package:http/http.dart' as http;
import 'package:cached_network_image/cached_network_image.dart';

// --- FIREBASE IMPORTS ---
import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:google_sign_in/google_sign_in.dart';
import 'package:firebase_messaging/firebase_messaging.dart';

// --- PRIOWAY API ---
import 'services/prioway_api_service.dart';
import 'services/notification_service.dart';

// --- FCM BACKGROUND HANDLER ---
@pragma('vm:entry-point')
Future<void> _firebaseMessagingBackgroundHandler(RemoteMessage message) async {
  await Firebase.initializeApp();
  debugPrint("Handling a background message: ${message.messageId}");
}

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Firebase.initializeApp();

  // Register background handler
  FirebaseMessaging.onBackgroundMessage(_firebaseMessagingBackgroundHandler);

  runApp(const PrioWayApp());
}

class PrioWayApp extends StatelessWidget {
  const PrioWayApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'PrioWay',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        scaffoldBackgroundColor: const Color(0xFF0A0A0A),
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFFFF3333),
          brightness: Brightness.dark,
        ),
        useMaterial3: true,
      ),
      home: const AuthWrapper(),
    );
  }
}

// --------------------------------------------------------
// PREMIUM UI ENGINE (CUSTOM ANIMATIONS & SHIMMER)
// --------------------------------------------------------
class FadeIn extends StatelessWidget {
  final Widget child;
  final double delay;

  const FadeIn({super.key, required this.child, this.delay = 0});

  @override
  Widget build(BuildContext context) {
    return TweenAnimationBuilder(
      tween: Tween<double>(begin: 0, end: 1),
      duration: const Duration(milliseconds: 600),
      curve: Curves.easeOutCubic,
      builder: (context, double value, child) {
        if (value < (delay * 0.1)) return const SizedBox.shrink();
        double normalizedValue = (value - (delay * 0.1)) / (1 - (delay * 0.1));
        normalizedValue = normalizedValue.clamp(0.0, 1.0);

        return Opacity(
          opacity: normalizedValue,
          child: Transform.translate(
            offset: Offset(0, 20 * (1 - normalizedValue)),
            child: child,
          ),
        );
      },
      child: child,
    );
  }
}

class ShimmerLoading extends StatefulWidget {
  final Widget child;
  const ShimmerLoading({super.key, required this.child});

  @override
  State<ShimmerLoading> createState() => _ShimmerLoadingState();
}

class _ShimmerLoadingState extends State<ShimmerLoading>
    with SingleTickerProviderStateMixin {
  late AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(vsync: this, duration: const Duration(seconds: 1))
      ..repeat(reverse: true);
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _controller,
      builder: (context, child) {
        return Opacity(
          opacity: _controller.value * 0.5 + 0.3,
          child: child,
        );
      },
      child: widget.child,
    );
  }
}

// --------------------------------------------------------
// GLOBAL SHARING FUNCTION
// --------------------------------------------------------
Future<void> shareBadgeAsset(String assetPath, String text) async {
  try {
    final ByteData bytes = await rootBundle.load(assetPath);
    final Uint8List list = bytes.buffer.asUint8List();
    final tempDir = Directory.systemTemp;
    final file =
        await File('${tempDir.path}/shared_badge.png').create(recursive: true);
    file.writeAsBytesSync(list);

    // ignore: deprecated_member_use
    await Share.shareXFiles(
      [XFile(file.path, mimeType: 'image/png')],
      text: text,
    );
  } catch (e) {
    debugPrint("Sharing error: $e");
  }
}

// --------------------------------------------------------
// AUTHENTICATION WRAPPER
// --------------------------------------------------------
class AuthWrapper extends StatelessWidget {
  const AuthWrapper({super.key});

  @override
  Widget build(BuildContext context) {
    return StreamBuilder<User?>(
      stream: FirebaseAuth.instance.authStateChanges(),
      builder: (context, snapshot) {
        if (snapshot.connectionState == ConnectionState.waiting) {
          return const Scaffold(
              body: Center(
                  child: CircularProgressIndicator(color: Color(0xFFFF3333))));
        }
        if (snapshot.hasData) {
          return const MainNavigationHub();
        }
        return const LoginScreen();
      },
    );
  }
}

// --------------------------------------------------------
// SCREEN 0: LOGIN
// --------------------------------------------------------
class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  bool _isSigningIn = false;

  Future<void> _signInWithGoogle() async {
    setState(() => _isSigningIn = true);
    try {
      final googleSignIn = GoogleSignIn.instance;
      await googleSignIn.initialize(
        serverClientId: '496036570061-1f61vmos46or3rkbfitatnm4vjtb9f56.apps.googleusercontent.com'
      );

      // Removed dead code: if user cancels, authenticate() throws a PlatformException caught below
      final googleUser = await googleSignIn.authenticate();
      final googleAuth = googleUser.authentication;
      final AuthCredential credential =
          GoogleAuthProvider.credential(idToken: googleAuth.idToken);

      UserCredential userCred =
          await FirebaseAuth.instance.signInWithCredential(credential);
      final userRef =
          FirebaseFirestore.instance.collection('users').doc(userCred.user!.uid);
      final doc = await userRef.get();

      if (!doc.exists) {
        await userRef.set({
          'name': userCred.user!.displayName ?? 'Unknown Scout',
          'email': userCred.user!.email,
          'photoUrl': userCred.user!.photoURL,
          'points': 0,
          'reports_count': 0,
          'has_seen_welcome': false,
          'joined_at': FieldValue.serverTimestamp(),
        });
      }
    } catch (e) {
      if (e is PlatformException && e.code == 'sign_in_canceled') {
        setState(() => _isSigningIn = false);
        return;
      }

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text('Auth Error: $e'), backgroundColor: Colors.redAccent));
      }
      setState(() => _isSigningIn = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(32.0),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Spacer(),
              FadeIn(
                child: Image.asset(
                  'assets/logo_transparent.png',
                  height: 90,
                  errorBuilder: (context, error, stackTrace) =>
                      const Icon(Icons.route, color: Color(0xFFFF3333), size: 90),
                ),
              ),
              const Spacer(),
              FadeIn(
                delay: 1,
                child: SizedBox(
                  width: double.infinity,
                  height: 60,
                  child: ElevatedButton.icon(
                    onPressed: _isSigningIn ? null : _signInWithGoogle,
                    icon: _isSigningIn
                        ? const SizedBox(
                            width: 24,
                            height: 24,
                            child: CircularProgressIndicator(
                                color: Colors.black, strokeWidth: 2))
                        : const Icon(Icons.g_mobiledata,
                            size: 40, color: Colors.black),
                    label: Text(
                        _isSigningIn ? 'Authenticating...' : 'Sign in with Google',
                        style: const TextStyle(
                            color: Colors.black,
                            fontSize: 18,
                            fontWeight: FontWeight.bold)),
                    style: ElevatedButton.styleFrom(
                        backgroundColor: Colors.white,
                        shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(12))),
                  ),
                ),
              ),
              const SizedBox(height: 20),
            ],
          ),
        ),
      ),
    );
  }
}

// --------------------------------------------------------
// NAVIGATION HUB & BADGE TRIGGER
// --------------------------------------------------------
class MainNavigationHub extends StatefulWidget {
  const MainNavigationHub({super.key});

  @override
  State<MainNavigationHub> createState() => _MainNavigationHubState();
}

class _MainNavigationHubState extends State<MainNavigationHub> {
  int _selectedIndex = 0;

  @override
  void initState() {
    super.initState();
    _checkWelcomeBadge();
    // Start FCM securely with mounted check
    Future.microtask(() {
      if (mounted) NotificationService.initialize(context);
    });
  }

  Future<void> _checkWelcomeBadge() async {
    final user = FirebaseAuth.instance.currentUser;
    if (user == null) return;

    final docRef = FirebaseFirestore.instance.collection('users').doc(user.uid);

    for (int i = 0; i < 3; i++) {
      await Future.delayed(const Duration(seconds: 1));
      if (!mounted) return;

      final doc = await docRef.get();
      if (doc.exists) {
        final data = doc.data() as Map<String, dynamic>;

        if (data['has_seen_welcome'] == false) {
          await docRef.update({'has_seen_welcome': true});
          if (!mounted) return; // Fix for context.mounted warning inside State
          
          showDialog(
            context: context,
            barrierDismissible: false,
            builder: (ctx) => AlertDialog(
              backgroundColor: const Color(0xFF1A1A1A),
              contentPadding: const EdgeInsets.all(24),
              shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(20),
                  side: const BorderSide(color: Color(0xFFFF3333), width: 1)),
              content: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(Icons.check_circle_outline,
                      color: Color(0xFFFF3333), size: 60),
                  const SizedBox(height: 16),
                  const Text('Network Connected',
                      style: TextStyle(
                          color: Colors.white,
                          fontSize: 22,
                          fontWeight: FontWeight.bold)),
                  const SizedBox(height: 20),
                  Image.asset('assets/badge_welcome.png',
                      height: 150,
                      errorBuilder: (c, e, s) => const Icon(Icons.shield,
                          size: 100, color: Color(0xFFFF3333))),
                  const SizedBox(height: 20),
                  const Text(
                      'You have successfully started contributing to PrioWay. The grid is active.',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: Colors.grey, height: 1.5)),
                  const SizedBox(height: 24),
                  ElevatedButton.icon(
                    style: ElevatedButton.styleFrom(
                        backgroundColor: const Color(0xFFFF3333),
                        minimumSize: const Size(double.infinity, 50)),
                    onPressed: () {
                      shareBadgeAsset('assets/badge_welcome.png',
                          'I just joined the PrioWay Network to map gridlocks and clear paths for emergency vehicles! #PrioWay');
                    },
                    icon: const Icon(Icons.share, color: Colors.white),
                    label: const Text('Flex on Social',
                      style: TextStyle(
                          color: Colors.white, fontWeight: FontWeight.bold)),
                  ),
                  const SizedBox(height: 8),
                  TextButton(
                      onPressed: () => Navigator.pop(ctx),
                      child: const Text('Continue to HQ',
                          style: TextStyle(color: Colors.grey))),
                ],
              ),
            ),
          );
          break;
        } else {
          break;
        }
      }
    }
  }

  void _onItemTapped(int index) => setState(() => _selectedIndex = index);

  Widget _buildScreen(int index) {
    switch (index) {
      case 0:
        return DashboardScreen(onNavigate: _onItemTapped);
      case 1:
        return const FullMapScreen();
      case 2:
        return const ReportScreen();
      case 3:
        return const LeaderboardScreen();
      case 4:
        return const ProfileScreen();
      default:
        return DashboardScreen(onNavigate: _onItemTapped);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: AnimatedSwitcher(
        duration: const Duration(milliseconds: 300),
        child: _buildScreen(_selectedIndex),
      ),
      bottomNavigationBar: BottomNavigationBar(
        backgroundColor: const Color(0xFF0A0A0A),
        type: BottomNavigationBarType.fixed,
        currentIndex: _selectedIndex,
        selectedItemColor: const Color(0xFFFF3333),
        unselectedItemColor: Colors.grey.shade700,
        onTap: _onItemTapped,
        items: const [
          BottomNavigationBarItem(icon: Icon(Icons.dashboard), label: 'Home'),
          BottomNavigationBarItem(icon: Icon(Icons.map), label: 'Map'),
          BottomNavigationBarItem(icon: Icon(Icons.camera_alt), label: 'Report'),
          BottomNavigationBarItem(icon: Icon(Icons.leaderboard), label: 'Rank'),
          BottomNavigationBarItem(icon: Icon(Icons.person), label: 'Profile'),
        ],
      ),
    );
  }
}

// --------------------------------------------------------
// COMMANDER MODE (ADMIN HQ & MODERATION)
// --------------------------------------------------------
class AdminDashboardScreen extends StatelessWidget {
  const AdminDashboardScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return DefaultTabController(
      length: 2,
      child: Scaffold(
        appBar: AppBar(
          backgroundColor: const Color(0xFF1A1A1A),
          title: const Text('Commander HQ',
              style: TextStyle(
                  color: Color(0xFFFF3333), fontWeight: FontWeight.bold)),
          iconTheme: const IconThemeData(color: Colors.white),
          bottom: const TabBar(
            indicatorColor: Color(0xFFFF3333),
            labelColor: Color(0xFFFF3333),
            unselectedLabelColor: Colors.grey,
            tabs: [
              Tab(icon: Icon(Icons.campaign), text: "Broadcast"),
              Tab(icon: Icon(Icons.gavel), text: "Moderation"),
            ],
          ),
        ),
        body: const TabBarView(
          children: [
            _BroadcastTab(),
            _ModerationTab(),
          ],
        ),
      ),
    );
  }
}

class _BroadcastTab extends StatefulWidget {
  const _BroadcastTab();

  @override
  State<_BroadcastTab> createState() => _BroadcastTabState();
}

class _BroadcastTabState extends State<_BroadcastTab> {
  final TextEditingController _titleController = TextEditingController();
  final TextEditingController _contentController = TextEditingController();
  File? _broadcastImage;
  final ImagePicker _picker = ImagePicker();
  bool _isBroadcasting = false;
  bool _isPickerActive = false;
  final String imgBBKey = '2d274c31415b92fa17f0c3eec2c7b981';

  Future<void> _pickImage() async {
    if (_isPickerActive) return;
    setState(() => _isPickerActive = true);
    try {
      final XFile? photo = await _picker.pickImage(
          source: ImageSource.gallery, imageQuality: 80);
      if (photo != null) setState(() => _broadcastImage = File(photo.path));
    } finally {
      setState(() => _isPickerActive = false);
    }
  }

  Future<void> _sendBroadcast() async {
    if (_titleController.text.isEmpty || _contentController.text.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('Title and Content are required.'),
          backgroundColor: Colors.orange));
      return;
    }

    setState(() => _isBroadcasting = true);

    try {
      String imageUrl = '';
      if (_broadcastImage != null) {
        var request = http.MultipartRequest(
            'POST', Uri.parse('https://api.imgbb.com/1/upload?key=$imgBBKey'));
        request.files.add(await http.MultipartFile.fromPath(
            'image', _broadcastImage!.path));
        var response =
            await request.send().timeout(const Duration(seconds: 15));

        if (response.statusCode == 200) {
          var responseData = await response.stream.bytesToString();
          var jsonMap = jsonDecode(responseData);
          imageUrl = jsonMap['data']['url'];
        } else {
          throw Exception('ImgBB rejected the broadcast media.');
        }
      }

      await FirebaseFirestore.instance.collection('news').add({
        'title': _titleController.text,
        'content': _contentController.text,
        'image_url': imageUrl,
        'timestamp': FieldValue.serverTimestamp(),
      });

      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text('Broadcast sent to the network.'),
            backgroundColor: Color(0xFFFF3333)));
        Navigator.pop(context);
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text('Broadcast failed: $e'), backgroundColor: Colors.red));
      }
      setState(() => _isBroadcasting = false);
    }
  }

  @override
  void dispose() {
    _titleController.dispose();
    _contentController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(24.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Network Alert Details',
                style: TextStyle(color: Colors.grey, fontWeight: FontWeight.bold)),
            const SizedBox(height: 16),
            TextField(
              controller: _titleController,
              style: const TextStyle(color: Colors.white),
              decoration: InputDecoration(
                labelText: 'Broadcast Title',
                labelStyle: const TextStyle(color: Colors.grey),
                enabledBorder: OutlineInputBorder(
                    borderSide: const BorderSide(color: Colors.grey),
                    borderRadius: BorderRadius.circular(12)),
                focusedBorder: OutlineInputBorder(
                    borderSide: const BorderSide(color: Color(0xFFFF3333)),
                    borderRadius: BorderRadius.circular(12)),
              ),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _contentController,
              maxLines: 5,
              style: const TextStyle(color: Colors.white),
              decoration: InputDecoration(
                labelText: 'Transmission Content',
                labelStyle: const TextStyle(color: Colors.grey),
                enabledBorder: OutlineInputBorder(
                    borderSide: const BorderSide(color: Colors.grey),
                    borderRadius: BorderRadius.circular(12)),
                focusedBorder: OutlineInputBorder(
                    borderSide: const BorderSide(color: Color(0xFFFF3333)),
                    borderRadius: BorderRadius.circular(12)),
              ),
            ),
            const SizedBox(height: 24),
            const Text('Optional Media Attachment',
                style: TextStyle(color: Colors.grey, fontWeight: FontWeight.bold)),
            const SizedBox(height: 12),
            if (_broadcastImage != null)
              Stack(
                alignment: Alignment.topRight,
                children: [
                  ClipRRect(
                      borderRadius: BorderRadius.circular(12),
                      child: Image.file(_broadcastImage!,
                          width: double.infinity, height: 200, fit: BoxFit.cover)),
                  IconButton(
                      icon: const Icon(Icons.cancel,
                          color: Colors.redAccent, size: 30),
                      onPressed: () => setState(() => _broadcastImage = null)),
                ],
              )
            else
              InkWell(
                onTap: _pickImage,
                child: Container(
                  width: double.infinity,
                  height: 120,
                  decoration: BoxDecoration(
                      color: const Color(0xFF1A1A1A),
                      border: Border.all(color: Colors.grey.withValues(alpha: 0.3)),
                      borderRadius: BorderRadius.circular(12)),
                  child: const Column(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Icon(Icons.add_photo_alternate, color: Colors.grey, size: 40),
                      SizedBox(height: 8),
                      Text('Attach Image', style: TextStyle(color: Colors.grey)),
                    ],
                  ),
                ),
              ),
            const SizedBox(height: 40),
            SizedBox(
              width: double.infinity,
              height: 56,
              child: ElevatedButton.icon(
                onPressed: _isBroadcasting ? null : _sendBroadcast,
                style: ElevatedButton.styleFrom(
                    backgroundColor: const Color(0xFFFF3333),
                    shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12))),
                icon: _isBroadcasting
                    ? const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(
                            color: Colors.white, strokeWidth: 2))
                    : const Icon(Icons.send, color: Colors.white),
                label: Text(_isBroadcasting ? 'Transmitting...' : 'Send to Network',
                    style: const TextStyle(
                        color: Colors.white,
                        fontSize: 16,
                        fontWeight: FontWeight.bold)),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ModerationTab extends StatelessWidget {
  const _ModerationTab();

  Future<void> _penalizeUser(BuildContext context, String flagId, String reportId,
      String offendingUserId) async {
    try {
      final adminUser = FirebaseAuth.instance.currentUser;

      if (adminUser == null) {
        throw Exception('Admin session is not available.');
      }

      final idToken = await adminUser.getIdToken();

      if (idToken == null || idToken.isEmpty) {
        throw Exception('Could not verify the admin session.');
      }

      // Remove the Railway evidence first. The backend checks the
      // Firebase ID token and confirms that this is the configured admin.
      // A report with no linked Railway evidence is still treated as a
      // successful no-op, which keeps older reports compatible.
      await PrioWayApiService.deleteEvidenceForReport(
        reportId: reportId,
        idToken: idToken,
      );

      await FirebaseFirestore.instance
          .collection('reports')
          .doc(reportId)
          .delete();

      await FirebaseFirestore.instance
          .collection('users')
          .doc(offendingUserId)
          .update({'points': FieldValue.increment(-150)});

      await FirebaseFirestore.instance
          .collection('flagged_intel')
          .doc(flagId)
          .delete();

      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
            content: Text('User penalized. Intel removed from app and PrioWay.'),
            backgroundColor: Color(0xFFFF3333)));
      }
    } catch (e) {
      if (context.mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text('Error: $e'), backgroundColor: Colors.red));
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    return StreamBuilder<QuerySnapshot>(
      stream: FirebaseFirestore.instance
          .collection('flagged_intel')
          .orderBy('timestamp', descending: true)
          .snapshots(),
      builder: (context, snapshot) {
        if (snapshot.connectionState == ConnectionState.waiting) {
          return const Center(
              child: CircularProgressIndicator(color: Color(0xFFFF3333)));
        }
        if (!snapshot.hasData || snapshot.data!.docs.isEmpty) {
          return const Center(
              child: Text("Queue is clean.", style: TextStyle(color: Colors.grey)));
        }

        return ListView.builder(
          padding: const EdgeInsets.all(16),
          itemCount: snapshot.data!.docs.length,
          itemBuilder: (context, index) {
            var doc = snapshot.data!.docs[index];
            var data = doc.data() as Map<String, dynamic>;

            return Card(
              color: const Color(0xFF1A1A1A),
              margin: const EdgeInsets.only(bottom: 16),
              child: Padding(
                padding: const EdgeInsets.all(16.0),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        const Icon(Icons.flag, color: Colors.redAccent),
                        const SizedBox(width: 8),
                        Expanded(
                            child: Text(data['tag'] ?? 'Unknown Hazard',
                                style: const TextStyle(
                                    color: Colors.white,
                                    fontWeight: FontWeight.bold,
                                    fontSize: 18))),
                      ],
                    ),
                    const SizedBox(height: 12),
                    if (data['image_url'] != null &&
                        data['image_url'].toString().isNotEmpty)
                      ClipRRect(
                        borderRadius: BorderRadius.circular(8),
                        child: CachedNetworkImage(
                          imageUrl: data['image_url'],
                          height: 150,
                          width: double.infinity,
                          fit: BoxFit.cover,
                          placeholder: (c, u) => const SizedBox(
                              height: 150,
                              child: Center(child: CircularProgressIndicator())),
                        ),
                      ),
                    const SizedBox(height: 16),
                    Row(
                      children: [
                        Expanded(
                          child: OutlinedButton(
                            onPressed: () => FirebaseFirestore.instance
                                .collection('flagged_intel')
                                .doc(doc.id)
                                .delete(),
                            style: OutlinedButton.styleFrom(
                                side: const BorderSide(color: Colors.grey)),
                            child: const Text('Dismiss',
                                style: TextStyle(color: Colors.white)),
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: ElevatedButton(
                            onPressed: () => _penalizeUser(context, doc.id,
                                data['report_id'], data['offending_user']),
                            style: ElevatedButton.styleFrom(
                                backgroundColor: Colors.redAccent),
                            child: const Text('Penalize',
                                style: TextStyle(color: Colors.white)),
                          ),
                        ),
                      ],
                    )
                  ],
                ),
              ),
            );
          },
        );
      },
    );
  }
}

// --------------------------------------------------------
// FULL SCREEN IMAGE VIEWER
// --------------------------------------------------------
class FullScreenImage extends StatelessWidget {
  final String imageUrl;
  const FullScreenImage({super.key, required this.imageUrl});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
          backgroundColor: Colors.transparent,
          elevation: 0,
          iconTheme: const IconThemeData(color: Colors.white)),
      body: Center(
        child: InteractiveViewer(
          panEnabled: true,
          minScale: 1,
          maxScale: 4,
          child: CachedNetworkImage(
            imageUrl: imageUrl,
            placeholder: (context, url) => const CircularProgressIndicator(
                color: Color(0xFFFF3333)),
            errorWidget: (context, url, error) => const Icon(Icons.error,
                color: Colors.red, size: 50),
          ),
        ),
      ),
    );
  }
}

// --------------------------------------------------------
// SCREEN 1: DASHBOARD
// --------------------------------------------------------
class DashboardScreen extends StatelessWidget {
  final Function(int) onNavigate;

  const DashboardScreen({super.key, required this.onNavigate});

  @override
  Widget build(BuildContext context) {
    final currentUserEmail = FirebaseAuth.instance.currentUser?.email;
    final isAdmin = currentUserEmail == 'soultk1977@gmail.com';

    return SafeArea(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.all(20.0),
            child: Row(
              children: [
                Image.asset('assets/logo_transparent.png',
                    height: 40,
                    errorBuilder: (ctx, err, stack) =>
                        const Icon(Icons.route, color: Color(0xFFFF3333), size: 40)),
                const Spacer(),
                if (isAdmin)
                  IconButton(
                    icon: const Icon(Icons.admin_panel_settings,
                        color: Color(0xFFFF3333), size: 32),
                    onPressed: () => Navigator.push(
                        context,
                        MaterialPageRoute(
                            builder: (_) => const AdminDashboardScreen())),
                  ),
              ],
            ),
          ),
          const Padding(
            padding: EdgeInsets.symmetric(horizontal: 20.0),
            child: Text('Live Network Updates',
                style: TextStyle(
                    color: Colors.grey,
                    fontSize: 14,
                    fontWeight: FontWeight.bold,
                    letterSpacing: 1.5)),
          ),
          const SizedBox(height: 16),
          Expanded(
            child: StreamBuilder<QuerySnapshot>(
              stream: FirebaseFirestore.instance
                  .collection('news')
                  .orderBy('timestamp', descending: true)
                  .snapshots(),
              builder: (context, snapshot) {
                if (snapshot.connectionState == ConnectionState.waiting) {
                  return ListView.builder(
                    padding: const EdgeInsets.symmetric(horizontal: 20),
                    itemCount: 3,
                    itemBuilder: (ctx, i) => ShimmerLoading(
                      child: Container(
                          margin: const EdgeInsets.only(bottom: 16),
                          height: 100,
                          decoration: BoxDecoration(
                              color: const Color(0xFF1A1A1A),
                              borderRadius: BorderRadius.circular(16))),
                    ),
                  );
                }

                if (!snapshot.hasData || snapshot.data!.docs.isEmpty) {
                  return Center(
                    child: FadeIn(
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Icon(Icons.cell_tower,
                              color: Colors.grey.withValues(alpha: 0.5), size: 60),
                          const SizedBox(height: 16),
                          const Text('No active transmissions.',
                              style: TextStyle(color: Colors.grey)),
                        ],
                      ),
                    ),
                  );
                }

                return ListView.builder(
                  padding: const EdgeInsets.symmetric(horizontal: 20),
                  itemCount: snapshot.data!.docs.length,
                  itemBuilder: (context, index) {
                    var data =
                        snapshot.data!.docs[index].data() as Map<String, dynamic>;
                    String? imageUrl =
                        data.containsKey('image_url') ? data['image_url'] : null;

                    return FadeIn(
                      delay: index.toDouble(),
                      child: Container(
                        margin: const EdgeInsets.only(bottom: 16),
                        padding: const EdgeInsets.all(20),
                        decoration: BoxDecoration(
                            color: const Color(0xFF1A1A1A),
                            borderRadius: BorderRadius.circular(16),
                            border: Border.all(
                                color: const Color(0xFFFF3333).withValues(alpha: 0.2))),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            if (imageUrl != null && imageUrl.isNotEmpty) ...[
                              GestureDetector(
                                onTap: () => Navigator.push(
                                    context,
                                    MaterialPageRoute(
                                        builder: (_) => FullScreenImage(
                                            imageUrl: imageUrl))),
                                child: Stack(
                                  alignment: Alignment.bottomRight,
                                  children: [
                                    ClipRRect(
                                      borderRadius: BorderRadius.circular(12),
                                      child: CachedNetworkImage(
                                        imageUrl: imageUrl,
                                        width: double.infinity,
                                        fit: BoxFit.fitWidth,
                                        placeholder: (context, url) => const SizedBox(
                                            height: 160,
                                            child: Center(
                                                child: CircularProgressIndicator(
                                                    color: Color(0xFFFF3333)))),
                                        errorWidget: (context, url, error) =>
                                            const SizedBox.shrink(),
                                      ),
                                    ),
                                    Container(
                                      margin: const EdgeInsets.all(8),
                                      padding: const EdgeInsets.all(6),
                                      decoration: BoxDecoration(
                                          color: Colors.black.withValues(alpha: 0.7),
                                          shape: BoxShape.circle),
                                      child: const Icon(Icons.fullscreen,
                                          color: Colors.white, size: 20),
                                    )
                                  ],
                                ),
                              ),
                              const SizedBox(height: 16),
                            ],
                            Row(
                              children: [
                                const Icon(Icons.campaign,
                                    color: Color(0xFFFF3333), size: 24),
                                const SizedBox(width: 12),
                                Expanded(
                                    child: Text(data['title'] ?? 'Update',
                                        style: const TextStyle(
                                            color: Colors.white,
                                            fontSize: 18,
                                            fontWeight: FontWeight.bold))),
                              ],
                            ),
                            const SizedBox(height: 12),
                            Text(data['content'] ?? '',
                                style: const TextStyle(
                                    color: Colors.grey, fontSize: 14, height: 1.5)),
                          ],
                        ),
                      ),
                    );
                  },
                );
              },
            ),
          ),
        ],
      ),
    );
  }
}

// --------------------------------------------------------
// SCREEN 2: MAP
// --------------------------------------------------------
class FullMapScreen extends StatefulWidget {
  const FullMapScreen({super.key});

  @override
  State<FullMapScreen> createState() => _FullMapScreenState();
}

class _FullMapScreenState extends State<FullMapScreen> {
  final MapController _mapController = MapController();
  LatLng _currentPosition = const LatLng(28.6139, 77.2090);
  bool _isLoadingLocation = true;
  bool _showNearbyOnly = false;

  @override
  void initState() {
    super.initState();
    _determinePosition();
  }

  Future<void> _determinePosition() async {
    bool serviceEnabled = await Geolocator.isLocationServiceEnabled();
    if (!serviceEnabled) {
      setState(() => _isLoadingLocation = false);
      return;
    }

    LocationPermission permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
      if (permission == LocationPermission.denied) {
        setState(() => _isLoadingLocation = false);
        return;
      }
    }

    if (permission == LocationPermission.deniedForever) {
      setState(() => _isLoadingLocation = false);
      _showPermissionDialog();
      return;
    }

    Position position = await Geolocator.getCurrentPosition();
    if (mounted) {
      setState(() {
        _currentPosition = LatLng(position.latitude, position.longitude);
        _isLoadingLocation = false;
      });
      _mapController.move(_currentPosition, 14.0);
    }
  }

  void _showPermissionDialog() {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: const Color(0xFF1A1A1A),
        title: const Text('Location Required',
            style: TextStyle(color: Colors.white)),
        content: const Text(
            'PrioWay requires precise GPS to map gridlocks. Please enable location permissions in your device settings.',
            style: TextStyle(color: Colors.grey)),
        actions: [
          TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Cancel')),
          ElevatedButton(
            style: ElevatedButton.styleFrom(
                backgroundColor: const Color(0xFFFF3333)),
            onPressed: () {
              Navigator.pop(ctx);
              Geolocator.openAppSettings();
            },
            child: const Text('Open Settings',
                style: TextStyle(color: Colors.white)),
          ),
        ],
      ),
    );
  }

  void _flyToReport(GeoPoint geo) =>
      _mapController.move(LatLng(geo.latitude, geo.longitude), 16.0);

  Future<void> _reportFakeIntel(
      String reportId, String offendingUserId, String? imageUrl, String? tag) async {
    Navigator.pop(context);
    await FirebaseFirestore.instance.collection('flagged_intel').add({
      'report_id': reportId,
      'offending_user': offendingUserId,
      'flagged_by': FirebaseAuth.instance.currentUser!.uid,
      'image_url': imageUrl,
      'tag': tag,
      'timestamp': FieldValue.serverTimestamp(),
    });
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
          content: Text('Intel flagged for admin review.'),
          backgroundColor: Colors.orange));
    }
  }

  void _showReportDetails(String docId, Map<String, dynamic> data) {
    showModalBottomSheet(
      context: context,
      backgroundColor: const Color(0xFF1A1A1A),
      isScrollControlled: true,
      shape: const RoundedRectangleBorder(
          borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (context) {
        return Padding(
          padding: const EdgeInsets.all(24.0),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Icon(Icons.warning_amber_rounded,
                      color: Colors.redAccent, size: 32),
                  const SizedBox(width: 12),
                  Expanded(
                      child: Text(data['tag'] ?? 'Hazard Reported',
                          style: const TextStyle(
                              color: Colors.white,
                              fontSize: 22,
                              fontWeight: FontWeight.bold))),
                ],
              ),
              const SizedBox(height: 16),
              if (data['image_url'] != null &&
                  data['image_url'].toString().isNotEmpty)
                ClipRRect(
                  borderRadius: BorderRadius.circular(12),
                  child: CachedNetworkImage(
                    imageUrl: data['image_url'],
                    width: double.infinity,
                    height: 250,
                    fit: BoxFit.cover,
                    placeholder: (context, url) => const SizedBox(
                        height: 250,
                        child: Center(
                            child: CircularProgressIndicator(
                                color: Color(0xFFFF3333)))),
                    errorWidget: (context, url, error) => Container(
                        height: 150,
                        color: Colors.black26,
                        child: const Center(
                            child: Text("Image failed to load",
                                style: TextStyle(color: Colors.red)))),
                  ),
                )
              else
                Container(
                  width: double.infinity,
                  height: 150,
                  decoration: BoxDecoration(
                      color: const Color(0xFF0A0A0A),
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: Colors.grey.withValues(alpha: 0.3))),
                  child: const Center(
                      child: Text('No Image Provided',
                          style: TextStyle(color: Colors.grey))),
                ),
              const SizedBox(height: 24),
              SizedBox(
                width: double.infinity,
                child: OutlinedButton.icon(
                  onPressed: () => _reportFakeIntel(docId, data['user_id'] ?? 'unknown',
                      data['image_url'], data['tag']),
                  icon: const Icon(Icons.flag, color: Colors.redAccent),
                  label: const Text('Report Fake Intel',
                      style: TextStyle(
                          color: Colors.redAccent, fontWeight: FontWeight.bold)),
                  style: OutlinedButton.styleFrom(
                      side: const BorderSide(color: Colors.redAccent),
                      padding: const EdgeInsets.symmetric(vertical: 14)),
                ),
              ),
              const SizedBox(height: 12),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton(
                  style: ElevatedButton.styleFrom(
                      backgroundColor: const Color(0xFFFF3333),
                      padding: const EdgeInsets.symmetric(vertical: 14)),
                  onPressed: () => Navigator.pop(context),
                  child: const Text('Close Scanner',
                      style: TextStyle(
                          color: Colors.white, fontWeight: FontWeight.bold)),
                ),
              )
            ],
          ),
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Stack(
        children: [
          StreamBuilder<QuerySnapshot>(
            stream: FirebaseFirestore.instance
                .collection('reports')
                .orderBy('timestamp', descending: true)
                .snapshots(),
            builder: (context, snapshot) {
              if (!snapshot.hasData) {
                return const Center(
                    child: CircularProgressIndicator(color: Color(0xFFFF3333)));
              }

              List<Marker> livePins = [];
              List<QueryDocumentSnapshot> visibleReports = [];
              DateTime now = DateTime.now();

              if (!_isLoadingLocation) {
                livePins.add(Marker(
                  point: _currentPosition,
                  width: 30,
                  height: 30,
                  child: Container(
                      decoration: BoxDecoration(
                          color: Colors.blueAccent,
                          shape: BoxShape.circle,
                          border: Border.all(color: Colors.white, width: 3))),
                ));
              }

              for (var doc in snapshot.data!.docs) {
                var data = doc.data() as Map<String, dynamic>;
                if (data['location'] != null) {
                  Timestamp? ts = data['timestamp'] as Timestamp?;
                  if (ts != null && now.difference(ts.toDate()).inMinutes > 30) {
                    continue;
                  }

                  GeoPoint geo = data['location'];
                  double distance = Geolocator.distanceBetween(
                      _currentPosition.latitude,
                      _currentPosition.longitude,
                      geo.latitude,
                      geo.longitude);
                  if (_showNearbyOnly && distance > 2000) continue;

                  visibleReports.add(doc);

                  livePins.add(Marker(
                    point: LatLng(geo.latitude, geo.longitude),
                    width: 50,
                    height: 50,
                    child: GestureDetector(
                      onTap: () => _showReportDetails(doc.id, data),
                      child: const Icon(Icons.warning_rounded,
                          color: Colors.redAccent, size: 40),
                    ),
                  ));
                }
              }

              return Stack(
                children: [
                  FlutterMap(
                    mapController: _mapController,
                    options: MapOptions(
                        initialCenter: _currentPosition, initialZoom: 13.0),
                    children: [
                      TileLayer(
                        urlTemplate:
                            'https://{s}.tile.jawg.io/jawg-dark/{z}/{x}/{y}{r}.png?access-token=yBn08jEakTOctBXizNlunV3SZopFM1UA3f0mZxvcXaKDAWKehwmEvBidehsJaAOR',
                        subdomains: const ['a', 'b', 'c', 'd'],
                        userAgentPackageName: 'com.example.prioway',
                      ),
                      MarkerLayer(markers: livePins),
                    ],
                  ),
                  SafeArea(
                    child: Padding(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 16.0, vertical: 8.0),
                      child: Row(
                        children: [
                          ChoiceChip(
                              label: const Text('All Reports'),
                              selected: !_showNearbyOnly,
                              selectedColor: const Color(0xFFFF3333),
                              labelStyle: const TextStyle(
                                  color: Colors.white,
                                  fontWeight: FontWeight.bold),
                              onSelected: (val) =>
                                  setState(() => _showNearbyOnly = false)),
                          const SizedBox(width: 12),
                          ChoiceChip(
                              label: const Text('Nearby (< 2km)'),
                              selected: _showNearbyOnly,
                              selectedColor: const Color(0xFFFF3333),
                              labelStyle: const TextStyle(
                                  color: Colors.white,
                                  fontWeight: FontWeight.bold),
                              onSelected: (val) =>
                                  setState(() => _showNearbyOnly = true)),
                        ],
                      ),
                    ),
                  ),
                  SafeArea(
                    child: Padding(
                      padding: const EdgeInsets.only(top: 60.0),
                      child: SizedBox(
                        height: 90,
                        child: ListView.builder(
                          scrollDirection: Axis.horizontal,
                          padding: const EdgeInsets.symmetric(horizontal: 16),
                          itemCount: visibleReports.length,
                          itemBuilder: (context, index) {
                            var rData = visibleReports[index].data()
                                as Map<String, dynamic>;
                            GeoPoint rGeo = rData['location'];
                            return FadeIn(
                              delay: index.toDouble(),
                              child: GestureDetector(
                                onTap: () {
                                  _flyToReport(rGeo);
                                  _showReportDetails(
                                      visibleReports[index].id, rData);
                                },
                                child: Container(
                                  width: 200,
                                  margin: const EdgeInsets.only(right: 12),
                                  padding: const EdgeInsets.all(12),
                                  decoration: BoxDecoration(
                                      color: const Color(0xFF1A1A1A).withValues(alpha: 0.9),
                                      borderRadius: BorderRadius.circular(12),
                                      border: Border.all(
                                          color: Colors.grey.withValues(alpha: 0.3))),
                                  child: Column(
                                    crossAxisAlignment: CrossAxisAlignment.start,
                                    mainAxisAlignment: MainAxisAlignment.center,
                                    children: [
                                      Text(rData['tag'] ?? 'Hazard',
                                          style: const TextStyle(
                                              color: Color(0xFFFF3333),
                                              fontWeight: FontWeight.bold,
                                              fontSize: 14),
                                          maxLines: 1,
                                          overflow: TextOverflow.ellipsis),
                                      const SizedBox(height: 4),
                                      const Text('Tap to view intel',
                                          style: TextStyle(
                                              color: Colors.grey, fontSize: 12)),
                                    ],
                                  ),
                                ),
                              ),
                            );
                          },
                        ),
                      ),
                    ),
                  ),
                ],
              );
            },
          ),
          if (_isLoadingLocation)
            const Center(
                child: CircularProgressIndicator(color: Color(0xFFFF3333))),
        ],
      ),
      floatingActionButton: FadeIn(
        delay: 5,
        child: FloatingActionButton(
          heroTag: "locateBtn",
          onPressed: _determinePosition,
          backgroundColor: const Color(0xFF1A1A1A),
          child: const Icon(Icons.my_location, color: Colors.white),
        ),
      ),
    );
  }
}

// --------------------------------------------------------
// SCREEN 3: REPORT
// --------------------------------------------------------
class ReportScreen extends StatefulWidget {
  const ReportScreen({super.key});

  @override
  State<ReportScreen> createState() => _ReportScreenState();
}

class _ReportScreenState extends State<ReportScreen> {
  File? _imageFile;
  final ImagePicker _picker = ImagePicker();
  String _selectedTag = "Stationary Traffic";
  final TextEditingController _customTagController = TextEditingController();
  bool _isUploading = false;
  bool _isPickerActive = false;

  final String imgBBKey = '2d274c31415b92fa17f0c3eec2c7b981';
  final List<String> _tags = [
    "Stationary Traffic",
    "Road Blockage",
    "Slow Moving",
    "Other"
  ];

  Future<void> _openCamera() async {
    if (_isPickerActive) return;
    setState(() => _isPickerActive = true);
    try {
      final XFile? photo =
          await _picker.pickImage(source: ImageSource.camera, imageQuality: 70);
      if (photo != null) {
        setState(() {
          _imageFile = File(photo.path);
          _selectedTag = "Stationary Traffic";
          _customTagController.clear();
        });
      }
    } finally {
      setState(() => _isPickerActive = false);
    }
  }

  Future<void> _submitIntel() async {
    setState(() => _isUploading = true);
    try {
      final uid = FirebaseAuth.instance.currentUser!.uid;
      final userDocRef = FirebaseFirestore.instance.collection('users').doc(uid);
      final userDoc = await userDocRef.get();

      if (userDoc.exists) {
        final data = userDoc.data() as Map<String, dynamic>;
        if (data.containsKey('last_report_time') &&
            data['last_report_time'] != null) {
          DateTime lastReport = (data['last_report_time'] as Timestamp).toDate();
          if (DateTime.now().difference(lastReport).inMinutes < 3) {
            setState(() => _isUploading = false);
            if (mounted) {
              ScaffoldMessenger.of(context).showSnackBar(const SnackBar(
                  content: Text(
                      'Network cooldown active. Please wait 3 minutes before submitting another report.'),
                  backgroundColor: Colors.orangeAccent));
            }
            return;
          }
        }
      }

      Position position = await Geolocator.getCurrentPosition();
      String finalTag =
          _selectedTag == "Other" ? _customTagController.text : _selectedTag;

      String imageUrl = '';
      if (_imageFile != null) {
        var request = http.MultipartRequest(
            'POST', Uri.parse('https://api.imgbb.com/1/upload?key=$imgBBKey'));
        request.files.add(
            await http.MultipartFile.fromPath('image', _imageFile!.path));
        var response = await request.send().timeout(const Duration(seconds: 15),
            onTimeout: () =>
                throw Exception("Connection timeout. The grid is congested."));
        if (response.statusCode == 200) {
          var responseData = await response.stream.bytesToString();
          imageUrl = jsonDecode(responseData)['data']['url'];
        } else {
          throw Exception('ImgBB rejected the image upload.');
        }
      }

      int currentPoints = userDoc.data()?['points'] ?? 0;
      int newPoints = currentPoints + 150;
      bool justUnlockedVanguard = (currentPoints < 500 && newPoints >= 500);

      final reportRef =
          await FirebaseFirestore.instance.collection('reports').add({
        'user_id': uid,
        'tag': finalTag,
        'image_url': imageUrl,
        'location': GeoPoint(position.latitude, position.longitude),
        'timestamp': FieldValue.serverTimestamp(),
      });

      await userDocRef.update({
        'points': FieldValue.increment(150),
        'reports_count': FieldValue.increment(1),
        'last_report_time': FieldValue.serverTimestamp(),
      });

      // --- PRIOWAY API INTEGRATION ---
      // Wait briefly for the Railway copy so the Firestore report ID
      // is linked before the report is shown as successfully submitted.
      // A Railway problem does not destroy the existing Firestore flow.
      try {
        await PrioWayApiService.uploadEvidence(
          file: _imageFile!,
          userId: uid,
          requestId: reportRef.id,
          description: finalTag,
        );
      } catch (e) {
        debugPrint("Flask Evidence Upload Error: $e");
      }
      // -------------------------------

      if (mounted) {
        setState(() {
          _isUploading = false;
          _imageFile = null;
        });
        Navigator.push(
            context,
            MaterialPageRoute(
                builder: (context) => ReportSuccessScreen(
                    newPoints: newPoints, unlockedVanguard: justUnlockedVanguard)));
      }
    } catch (e) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(
            content: Text('Upload failed: $e'), backgroundColor: Colors.red));
      }
      setState(() => _isUploading = false);
    }
  }

  @override
  void dispose() {
    _customTagController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (_imageFile == null) {
      return SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(20.0),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              FadeIn(
                  child: const Icon(Icons.camera_alt_outlined,
                      color: Colors.grey, size: 80)),
              const SizedBox(height: 20),
              const FadeIn(
                  delay: 1,
                  child: Text('Visual Intel Required',
                      style: TextStyle(
                          color: Colors.white,
                          fontSize: 24,
                          fontWeight: FontWeight.bold))),
              const SizedBox(height: 16),
              const FadeIn(
                  delay: 2,
                  child: Text(
                      'Capture clear visual proof of the emergency vehicle or traffic blockage to validate your report.',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: Colors.grey, fontSize: 16))),
              const SizedBox(height: 40),
              FadeIn(
                delay: 3,
                child: SizedBox(
                  width: double.infinity,
                  height: 60,
                  child: ElevatedButton.icon(
                    onPressed: _openCamera,
                    icon: const Icon(Icons.camera, color: Colors.white),
                    label: const Text('Open Camera',
                        style: TextStyle(
                            color: Colors.white,
                            fontSize: 18,
                            fontWeight: FontWeight.bold)),
                    style: ElevatedButton.styleFrom(
                        backgroundColor: const Color(0xFFFF3333),
                        shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(12))),
                  ),
                ),
              ),
            ],
          ),
        ),
      );
    }

    return SafeArea(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(20.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const FadeIn(
                child: Text('Verify & Tag Intel',
                    style: TextStyle(
                        color: Color(0xFFFF3333),
                        fontSize: 24,
                        fontWeight: FontWeight.bold))),
            const SizedBox(height: 20),
            FadeIn(
              delay: 1,
              child: ClipRRect(
                borderRadius: BorderRadius.circular(16),
                child: Stack(
                  alignment: Alignment.bottomCenter,
                  children: [
                    Image.file(_imageFile!,
                        width: double.infinity, height: 300, fit: BoxFit.cover),
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(12),
                      decoration: BoxDecoration(
                          gradient: LinearGradient(
                              begin: Alignment.bottomCenter,
                              end: Alignment.topCenter,
                              colors: [Colors.black.withValues(alpha: 0.9), Colors.transparent])),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                              _selectedTag == "Other" &&
                                      _customTagController.text.isNotEmpty
                                  ? _customTagController.text.toUpperCase()
                                  : _selectedTag.toUpperCase(),
                              style: const TextStyle(
                                  color: Color(0xFFFF3333),
                                  fontSize: 20,
                                  fontWeight: FontWeight.bold,
                                  letterSpacing: 1.2)),
                          const SizedBox(height: 4),
                          const Text('@PrioWay Network',
                              style: TextStyle(
                                  color: Colors.white,
                                  fontSize: 12,
                                  fontWeight: FontWeight.bold)),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: 32),
            const FadeIn(
                delay: 2,
                child: Text('Select Hazard Type',
                    style: TextStyle(
                        color: Colors.grey,
                        fontSize: 14,
                        fontWeight: FontWeight.bold))),
            const SizedBox(height: 12),
            FadeIn(
              delay: 3,
              child: Wrap(
                spacing: 10,
                runSpacing: 10,
                children: _tags.map((tag) {
                  bool isSelected = _selectedTag == tag;
                  return ChoiceChip(
                    label: Text(tag,
                        style: TextStyle(
                            color: isSelected ? Colors.white : Colors.white)),
                    selected: isSelected,
                    selectedColor: const Color(0xFFFF3333),
                    backgroundColor: const Color(0xFF1A1A1A),
                    onSelected: (selected) => setState(() => _selectedTag = tag),
                  );
                }).toList(),
              ),
            ),
            if (_selectedTag == "Other") ...[
              const SizedBox(height: 20),
              FadeIn(
                delay: 4,
                child: TextField(
                  controller: _customTagController,
                  style: const TextStyle(color: Colors.white),
                  onChanged: (value) => setState(() {}),
                  decoration: InputDecoration(
                      labelText: 'Describe the hazard',
                      labelStyle: const TextStyle(color: Colors.grey),
                      enabledBorder: OutlineInputBorder(
                          borderSide: const BorderSide(color: Colors.grey),
                          borderRadius: BorderRadius.circular(12)),
                      focusedBorder: OutlineInputBorder(
                          borderSide: const BorderSide(color: Color(0xFFFF3333)),
                          borderRadius: BorderRadius.circular(12))),
                ),
              ),
            ],
            const SizedBox(height: 40),
            FadeIn(
              delay: 5,
              child: Row(
                children: [
                  Expanded(
                    child: OutlinedButton(
                      onPressed: _isUploading
                          ? null
                          : () => setState(() => _imageFile = null),
                      style: OutlinedButton.styleFrom(
                          padding: const EdgeInsets.symmetric(vertical: 16),
                          side: const BorderSide(color: Colors.grey),
                          shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(12))),
                      child: const Text('Retake',
                          style: TextStyle(color: Colors.white, fontSize: 16)),
                    ),
                  ),
                  const SizedBox(width: 16),
                  Expanded(
                    flex: 2,
                    child: ElevatedButton(
                      onPressed: _isUploading ? null : _submitIntel,
                      style: ElevatedButton.styleFrom(
                          padding: const EdgeInsets.symmetric(vertical: 16),
                          backgroundColor: const Color(0xFFFF3333),
                          shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(12))),
                      child: _isUploading
                          ? const SizedBox(
                              width: 24,
                              height: 24,
                              child: CircularProgressIndicator(
                                  color: Colors.white, strokeWidth: 2))
                          : const Text('Submit Intel',
                              style: TextStyle(
                                  color: Colors.white,
                                  fontSize: 16,
                                  fontWeight: FontWeight.bold)),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class ReportSuccessScreen extends StatelessWidget {
  final int newPoints;
  final bool unlockedVanguard;

  const ReportSuccessScreen(
      {super.key, required this.newPoints, required this.unlockedVanguard});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: const Color(0xFF0A0A0A),
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24.0),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const FadeIn(
                  child: Icon(Icons.check_circle_outline,
                      color: Color(0xFFFF3333), size: 100)),
              const SizedBox(height: 24),
              const FadeIn(
                  delay: 1,
                  child: Text('Intel Live!',
                      style: TextStyle(
                          color: Colors.white,
                          fontSize: 32,
                          fontWeight: FontWeight.bold))),
              const SizedBox(height: 12),
              FadeIn(
                  delay: 2,
                  child: Text('You now have $newPoints total points.',
                      style: const TextStyle(color: Colors.grey, fontSize: 18))),
              const SizedBox(height: 40),
              if (unlockedVanguard) ...[
                FadeIn(
                  delay: 3,
                  child: Container(
                    padding: const EdgeInsets.all(20),
                    decoration: BoxDecoration(
                        border: Border.all(color: const Color(0xFFFFFFFF)),
                        borderRadius: BorderRadius.circular(16)),
                    child: const Column(
                      children: [
                        Row(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Icon(Icons.workspace_premium, color: Color(0xFFFFFFFF)),
                            SizedBox(width: 8),
                            Text('500 POINTS REACHED!',
                                style: TextStyle(
                                    color: Color(0xFFFFFFFF),
                                    fontSize: 18,
                                    fontWeight: FontWeight.bold)),
                          ],
                        ),
                        SizedBox(height: 8),
                        Text(
                            'You have unlocked Vanguard Scout status. Check your profile to view your new badge.',
                            textAlign: TextAlign.center,
                            style: TextStyle(color: Colors.white)),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 40),
              ],
              FadeIn(
                  delay: unlockedVanguard ? 4 : 3,
                  child: Image.asset('assets/badge_report.png',
                      height: 150,
                      errorBuilder: (c, e, s) =>
                          const Icon(Icons.camera_alt, size: 100, color: Colors.grey))),
              const SizedBox(height: 40),
              FadeIn(
                delay: unlockedVanguard ? 5 : 4,
                child: SizedBox(
                  width: double.infinity,
                  child: ElevatedButton.icon(
                    style: ElevatedButton.styleFrom(
                        backgroundColor: const Color(0xFFFF3333),
                        padding: const EdgeInsets.symmetric(vertical: 16)),
                    onPressed: () {
                      shareBadgeAsset('assets/badge_report.png',
                          'I just reported an obstacle and hit $newPoints points on the PrioWay Network! Join the grid.');
                    },
                    icon: const Icon(Icons.share, color: Colors.white),
                    label: const Text('Flex to Instagram',
                        style: TextStyle(
                            color: Colors.white,
                            fontSize: 18,
                            fontWeight: FontWeight.bold)),
                  ),
                ),
              ),
              const SizedBox(height: 16),
              FadeIn(
                  delay: unlockedVanguard ? 6 : 5,
                  child: TextButton(
                      onPressed: () => Navigator.pop(context),
                      child: const Text('Return to Map',
                          style: TextStyle(color: Colors.grey, fontSize: 16)))),
            ],
          ),
        ),
      ),
    );
  }
}

// --------------------------------------------------------
// SCREEN 4: LEADERBOARD
// --------------------------------------------------------
class LeaderboardScreen extends StatelessWidget {
  const LeaderboardScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.all(20.0),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('Network Rankings',
                style: TextStyle(
                    color: Color(0xFFFF3333),
                    fontSize: 28,
                    fontWeight: FontWeight.bold)),
            const SizedBox(height: 8),
            const Text('Global Scout Standings',
                style: TextStyle(color: Colors.grey, fontSize: 14)),
            const SizedBox(height: 24),
            Expanded(
              child: StreamBuilder<QuerySnapshot>(
                stream: FirebaseFirestore.instance
                    .collection('users')
                    .orderBy('points', descending: true)
                    .limit(10)
                    .snapshots(),
                builder: (context, snapshot) {
                  if (snapshot.connectionState == ConnectionState.waiting) {
                    return ListView.builder(
                      itemCount: 5,
                      itemBuilder: (ctx, i) => ShimmerLoading(
                        child: Container(
                            margin: const EdgeInsets.only(bottom: 12),
                            height: 70,
                            decoration: BoxDecoration(
                                color: const Color(0xFF1A1A1A),
                                borderRadius: BorderRadius.circular(12))),
                      ),
                    );
                  }

                  if (!snapshot.hasData || snapshot.data!.docs.isEmpty) {
                    return const Center(
                        child: Text("No scouts ranked yet.",
                            style: TextStyle(color: Colors.grey)));
                  }

                  return ListView.builder(
                    itemCount: snapshot.data!.docs.length,
                    itemBuilder: (context, index) {
                      var userData = snapshot.data!.docs[index].data()
                          as Map<String, dynamic>;
                      bool isTopThree = index < 3;

                      return FadeIn(
                        delay: index.toDouble(),
                        child: Container(
                          margin: const EdgeInsets.only(bottom: 12),
                          padding: const EdgeInsets.all(16),
                          decoration: BoxDecoration(
                            color: isTopThree
                                ? const Color(0xFF1A1A1A)
                                : Colors.transparent,
                            borderRadius: BorderRadius.circular(12),
                            border: isTopThree
                                ? Border.all(
                                    color: const Color(0xFFFF3333).withValues(alpha: 0.2))
                                : null,
                          ),
                          child: Row(
                            children: [
                              Text('#${index + 1}',
                                  style: TextStyle(
                                      color: isTopThree
                                          ? const Color(0xFFFF3333)
                                          : Colors.grey,
                                      fontSize: 18,
                                      fontWeight: FontWeight.bold)),
                              const SizedBox(width: 20),
                              CircleAvatar(
                                radius: 14,
                                backgroundColor: Colors.transparent,
                                backgroundImage: userData['photoUrl'] != null
                                    ? CachedNetworkImageProvider(
                                        userData['photoUrl'])
                                    : null,
                                child: userData['photoUrl'] == null
                                    ? Icon(Icons.person,
                                        color: isTopThree ? Colors.white : Colors.grey)
                                    : null,
                              ),
                              const SizedBox(width: 16),
                              Expanded(
                                  child: Text(userData['name'] ?? 'Unknown',
                                      style: TextStyle(
                                          color: isTopThree
                                              ? Colors.white
                                              : Colors.grey.shade400,
                                          fontSize: 16,
                                          fontWeight: FontWeight.bold))),
                              Text('${userData['points'] ?? 0} pts',
                                  style: const TextStyle(
                                      color: Color(0xFFFFFFFF),
                                      fontWeight: FontWeight.bold)),
                            ],
                          ),
                        ),
                      );
                    },
                  );
                },
              ),
            )
          ],
        ),
      ),
    );
  }
}

// --------------------------------------------------------
// SCREEN 5: PROFILE
// --------------------------------------------------------
class ProfileScreen extends StatelessWidget {
  const ProfileScreen({super.key});

  Future<void> _signOut() async {
    await GoogleSignIn.instance.disconnect();
    await FirebaseAuth.instance.signOut();
  }

  Future<void> _deleteAccount(BuildContext context) async {
    bool? confirm = await showDialog<bool>(
      context: context,
      builder: (BuildContext ctx) {
        return AlertDialog(
          backgroundColor: const Color(0xFF1A1A1A),
          title: const Text("Delete Account?",
              style: TextStyle(
                  color: Colors.redAccent, fontWeight: FontWeight.bold)),
          content: const Text(
              "This will permanently erase your profile, points, and all submitted intel from the PrioWay database. This cannot be undone.",
              style: TextStyle(color: Colors.white)),
          actions: [
            TextButton(
                onPressed: () => Navigator.of(ctx).pop(false),
                child:
                    const Text("Cancel", style: TextStyle(color: Colors.grey))),
            ElevatedButton(
              style: ElevatedButton.styleFrom(backgroundColor: Colors.redAccent),
              onPressed: () => Navigator.of(ctx).pop(true),
              child: const Text("Delete Everything",
                  style: TextStyle(
                      color: Colors.white, fontWeight: FontWeight.bold)),
            ),
          ],
        );
      },
    );

    if (confirm == true) {
      try {
        final user = FirebaseAuth.instance.currentUser;
        if (user != null) {
          final googleSignIn = GoogleSignIn.instance;

          // Removed dead code: if user cancels, authenticate() throws a PlatformException caught below
          final googleUser = await googleSignIn.authenticate();
          final googleAuth = googleUser.authentication;
          final credential = GoogleAuthProvider.credential(
              idToken: googleAuth.idToken);
          await user.reauthenticateWithCredential(credential);

          await FirebaseFirestore.instance
              .collection('users')
              .doc(user.uid)
              .delete();
          await user.delete();
          await googleSignIn.disconnect();
        }
      } catch (e) {
        if (context.mounted) {
          ScaffoldMessenger.of(context).showSnackBar(SnackBar(
              content: Text('Error deleting account: $e'),
              backgroundColor: Colors.red));
        }
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final user = FirebaseAuth.instance.currentUser!;

    return SafeArea(
      child: StreamBuilder<DocumentSnapshot>(
          stream: FirebaseFirestore.instance
              .collection('users')
              .doc(user.uid)
              .snapshots(),
          builder: (context, snapshot) {
            if (!snapshot.hasData) {
              return const Center(
                  child: CircularProgressIndicator(color: Color(0xFFFF3333)));
            }

            var userData = snapshot.data!.data() as Map<String, dynamic>? ?? {};
            int reportsCount = userData['reports_count'] ?? 0;
            int points = userData['points'] ?? 0;

            bool isVanguard = points >= 500;
            String tierTitle =
                isVanguard ? 'Vanguard Scout' : 'Verified Contributor';
            String tierAsset = isVanguard
                ? 'assets/badge_vanguard.png'
                : 'assets/badge_contributor.png';
            Color tierColor =
                isVanguard ? const Color(0xFFFFFFFF) : const Color(0xFFFF3333);

            return SingleChildScrollView(
              padding: const EdgeInsets.all(20.0),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.center,
                children: [
                  const SizedBox(height: 20),
                  FadeIn(
                    child: CircleAvatar(
                      radius: 50,
                      backgroundColor: const Color(0xFF1A1A1A),
                      backgroundImage: user.photoURL != null
                          ? CachedNetworkImageProvider(user.photoURL!)
                          : null,
                      child: user.photoURL == null
                          ? const Icon(Icons.person,
                              size: 50, color: Color(0xFFFF3333))
                          : null,
                    ),
                  ),
                  const SizedBox(height: 16),
                  FadeIn(
                      delay: 1,
                      child: Text(user.displayName ?? 'Active Scout',
                          style: const TextStyle(
                              color: Colors.white,
                              fontSize: 24,
                              fontWeight: FontWeight.bold))),
                  const SizedBox(height: 4),
                  FadeIn(
                      delay: 2,
                      child: Text(user.email ?? 'scout@prioway.net',
                          style:
                              const TextStyle(color: Colors.grey, fontSize: 14))),
                  const SizedBox(height: 32),
                  FadeIn(
                    delay: 3,
                    child: Container(
                      padding: const EdgeInsets.all(20),
                      decoration: BoxDecoration(
                          color: const Color(0xFF1A1A1A),
                          borderRadius: BorderRadius.circular(16)),
                      child: Row(
                        mainAxisAlignment: MainAxisAlignment.spaceAround,
                        children: [
                          _buildStatItem('Intel Pinned', '$reportsCount',
                              const Color(0xFFFF3333)),
                          Container(
                              height: 40, width: 1, color: Colors.grey.withValues(alpha: 0.3)),
                          _buildStatItem('Total Score', '$points', tierColor),
                        ],
                      ),
                    ),
                  ),
                  const SizedBox(height: 32),
                  const FadeIn(
                      delay: 4,
                      child: Align(
                          alignment: Alignment.centerLeft,
                          child: Text('Active Network Badge',
                              style: TextStyle(
                                  color: Colors.grey, fontWeight: FontWeight.bold)))),
                  const SizedBox(height: 12),
                  if (reportsCount > 0)
                    FadeIn(
                      delay: 5,
                      child: Container(
                        padding: const EdgeInsets.all(16),
                        decoration: BoxDecoration(
                            border: Border.all(color: tierColor.withValues(alpha: 0.5)),
                            color: const Color(0xFF1A1A1A),
                            borderRadius: BorderRadius.circular(16)),
                        child: Column(
                          children: [
                            Image.asset(tierAsset,
                                height: 120,
                                errorBuilder: (c, e, s) =>
                                    Icon(Icons.local_police, color: tierColor, size: 80)),
                            const SizedBox(height: 16),
                            Text(tierTitle,
                                style: TextStyle(
                                    color: tierColor,
                                    fontWeight: FontWeight.bold,
                                    fontSize: 20)),
                            const SizedBox(height: 4),
                            const Text('Verified PrioWay Contributor',
                                style:
                                    TextStyle(color: Colors.grey, fontSize: 12)),
                            const SizedBox(height: 16),
                            SizedBox(
                              width: double.infinity,
                              child: ElevatedButton.icon(
                                style: ElevatedButton.styleFrom(
                                    backgroundColor: tierColor),
                                onPressed: () => shareBadgeAsset(tierAsset,
                                    'I am a $tierTitle with $points points on the PrioWay Network!'),
                                icon: Icon(Icons.share,
                                    color:
                                        isVanguard ? Colors.black : Colors.white),
                                label: Text('Share Badge',
                                    style: TextStyle(
                                        color: isVanguard
                                            ? Colors.black
                                            : Colors.white,
                                        fontWeight: FontWeight.bold)),
                              ),
                            )
                          ],
                        ),
                      ),
                    )
                  else
                    FadeIn(
                      delay: 5,
                      child: Container(
                        width: double.infinity,
                        padding: const EdgeInsets.all(16),
                        decoration: BoxDecoration(
                            color: const Color(0xFF1A1A1A),
                            borderRadius: BorderRadius.circular(16)),
                        child: const Center(
                            child: Text('Submit intel to unlock your first badge.',
                                style: TextStyle(color: Colors.grey))),
                      ),
                    ),
                  const SizedBox(height: 40),
                  FadeIn(
                    delay: 6,
                    child: InkWell(
                      onTap: () => _deleteAccount(context),
                      borderRadius: BorderRadius.circular(12),
                      child: Padding(
                        padding: const EdgeInsets.symmetric(
                            vertical: 12.0, horizontal: 8.0),
                        child: Row(
                          children: const [
                            Icon(Icons.delete_forever,
                                color: Colors.redAccent, size: 24),
                            SizedBox(width: 16),
                            Text('Delete Account',
                                style: TextStyle(
                                    color: Colors.redAccent,
                                    fontSize: 16,
                                    fontWeight: FontWeight.bold)),
                            Spacer(),
                            Icon(Icons.arrow_forward_ios,
                                color: Colors.redAccent, size: 16),
                          ],
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(height: 40),
                  FadeIn(
                    delay: 7,
                    child: SizedBox(
                      width: double.infinity,
                      height: 56,
                      child: OutlinedButton.icon(
                        onPressed: _signOut,
                        icon: const Icon(Icons.logout, color: Colors.white),
                        label: const Text('Sign Out',
                            style: TextStyle(
                                color: Colors.white,
                                fontSize: 16,
                                fontWeight: FontWeight.bold)),
                        style: OutlinedButton.styleFrom(
                            side: const BorderSide(color: Colors.grey, width: 2),
                            shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(12))),
                      ),
                    ),
                  ),
                  const SizedBox(height: 20),
                ],
              ),
            );
          }),
    );
  }

  Widget _buildStatItem(String label, String value, Color color) {
    return Column(
      children: [
        Text(value,
            style: TextStyle(
                color: color, fontSize: 22, fontWeight: FontWeight.bold)),
        const SizedBox(height: 6),
        Text(label, style: const TextStyle(color: Colors.grey, fontSize: 12)),
      ],
    );
  }
}