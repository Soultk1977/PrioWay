import 'dart:async';

import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/material.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:geolocator/geolocator.dart';

import 'prioway_api_service.dart';


class NotificationService {
  static final FirebaseMessaging _messaging = FirebaseMessaging.instance;

  static bool _initialized = false;
  static bool _locationSendInProgress = false;

  static String? _currentToken;
  static Timer? _locationTimer;

  static Future<void> initialize(BuildContext context) async {
    if (_initialized) return;

    NotificationSettings settings = await _messaging.requestPermission(
      alert: true,
      badge: true,
      sound: true,
    );

    if (settings.authorizationStatus == AuthorizationStatus.authorized) {
      _initialized = true;

      await _registerToken();

      _messaging.onTokenRefresh.listen((newToken) {
        _currentToken = newToken;
        _sendTokenToBackend(newToken);
      });

      FirebaseMessaging.onMessage.listen((RemoteMessage message) {
        if (message.notification != null) {
          if (!context.mounted) return;

          ScaffoldMessenger.of(context).showSnackBar(
            SnackBar(
              content: Text(
                '${message.notification?.title}: ${message.notification?.body}',
              ),
              backgroundColor: const Color(0xFFFF3333),
              duration: const Duration(seconds: 4),
            ),
          );
        }
      });

      FirebaseMessaging.onMessageOpenedApp.listen((RemoteMessage message) {
        debugPrint(
          'App opened from background via notification: ${message.messageId}',
        );
      });

      _messaging.getInitialMessage().then((RemoteMessage? message) {
        if (message != null) {
          debugPrint(
            'App started from terminated state via notification: ${message.messageId}',
          );
        }
      });

      await _startLocationHeartbeat();
    }
  }

  static Future<void> _registerToken() async {
    try {
      final String? token = await _messaging.getToken();

      if (token != null && token.isNotEmpty) {
        _currentToken = token;
        await _sendTokenToBackend(token);
      }
    } catch (e) {
      debugPrint('FCM Token fetch failed: $e');
    }
  }

  static Future<void> _sendTokenToBackend(String token) async {
    final user = FirebaseAuth.instance.currentUser;

    if (user == null) return;

    try {
      await PrioWayApiService.registerDeviceToken(
        user.uid,
        token,
      );

      debugPrint('Token registered with PrioWay API');

      await _sendCurrentLocation();
    } catch (e) {
      debugPrint('PrioWay API Token Registration failed: $e');
    }
  }

  static Future<void> _startLocationHeartbeat() async {
    _locationTimer?.cancel();

    await _sendCurrentLocation();

    _locationTimer = Timer.periodic(
      const Duration(seconds: 30),
      (_) {
        _sendCurrentLocation();
      },
    );
  }

  static Future<bool> _locationPermissionAvailable() async {
    final serviceEnabled = await Geolocator.isLocationServiceEnabled();

    if (!serviceEnabled) {
      return false;
    }

    LocationPermission permission = await Geolocator.checkPermission();

    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
    }

    return permission != LocationPermission.denied &&
        permission != LocationPermission.deniedForever;
  }

  static Future<void> _sendCurrentLocation() async {
    if (_locationSendInProgress) return;

    final user = FirebaseAuth.instance.currentUser;
    final token = _currentToken;

    if (user == null || token == null || token.isEmpty) {
      return;
    }

    _locationSendInProgress = true;

    try {
      final permissionAvailable = await _locationPermissionAvailable();

      if (!permissionAvailable) {
        return;
      }

      final position = await Geolocator.getCurrentPosition();

      final idToken = await user.getIdToken();

      if (idToken == null || idToken.isEmpty) {
        return;
      }

      await PrioWayApiService.updateDeviceLocation(
        userId: user.uid,
        deviceToken: token,
        idToken: idToken,
        lat: position.latitude,
        lon: position.longitude,
        accuracyM: position.accuracy,
      );

      debugPrint(
        'PrioWay location heartbeat sent '
        '(${position.latitude}, ${position.longitude})',
      );
    } catch (e) {
      debugPrint('PrioWay location heartbeat failed: $e');
    } finally {
      _locationSendInProgress = false;
    }
  }
}
