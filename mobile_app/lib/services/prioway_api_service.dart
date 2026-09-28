import 'dart:convert';
import 'dart:io';
import 'package:http/http.dart' as http;
import '../config/api_config.dart';

class PrioWayApiException implements Exception {
  final String message;
  final int? statusCode;

  PrioWayApiException(this.message, [this.statusCode]);

  @override
  String toString() => 'PrioWayApiException: $message (Status: $statusCode)';
}

class PrioWayApiService {
  static const int _timeoutSeconds = 10;

  static Future<dynamic> _get(String endpoint) async {
    try {
      final response = await http
          .get(Uri.parse('${ApiConfig.baseUrl}$endpoint'))
          .timeout(const Duration(seconds: _timeoutSeconds));
      return _handleResponse(response);
    } catch (e) {
      _handleError(e);
    }
  }

  static Future<dynamic> _post(String endpoint, Map<String, dynamic> body) async {
    try {
      final response = await http
          .post(
            Uri.parse('${ApiConfig.baseUrl}$endpoint'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode(body),
          )
          .timeout(const Duration(seconds: _timeoutSeconds));
      return _handleResponse(response);
    } catch (e) {
      _handleError(e);
    }
  }

  static dynamic _handleResponse(http.Response response) {
    if (response.statusCode >= 200 && response.statusCode < 300) {
      if (response.body.isEmpty) return null;
      try {
        return jsonDecode(response.body);
      } catch (_) {
        throw PrioWayApiException('Invalid JSON response', response.statusCode);
      }
    } else {
      String errorMessage = 'API Error';
      try {
        final decoded = jsonDecode(response.body);
        if (decoded is Map) {
          if (decoded.containsKey('message')) {
            errorMessage = decoded['message'];
          } else if (decoded.containsKey('error')) {
            errorMessage = decoded['error'];
          }
        }
      } catch (_) {
        // Fallback to generic message if JSON parsing fails
      }
      throw PrioWayApiException(errorMessage, response.statusCode);
    }
  }

  static void _handleError(dynamic e) {
    if (e is PrioWayApiException) throw e;
    throw PrioWayApiException('Network/Timeout: ${e.toString()}');
  }

  // --- API METHODS ---

  static Future<dynamic> getHealth() => _get('/api/v1/health');
  
  static Future<dynamic> getStatus() => _get('/api/v1/status');
  
  static Future<dynamic> getVehicles() => _get('/api/v1/vehicles');
  
  static Future<dynamic> getVehicle(String vehicleId) => _get('/api/v1/vehicles/$vehicleId');
  
  static Future<dynamic> getVehicleLocation(String vehicleId) => _get('/api/v1/vehicles/$vehicleId/location');
  
  static Future<dynamic> getJunctions() => _get('/api/v1/junctions');
  
  static Future<dynamic> getJunction(String junctionId) => _get('/api/v1/junctions/$junctionId');
  
  static Future<dynamic> getRequests() => _get('/api/v1/requests');
  
  static Future<dynamic> createRequest(Map<String, dynamic> data) => _post('/api/v1/requests', data);
  
  static Future<dynamic> getRequest(String requestId) => _get('/api/v1/requests/$requestId');
  
  static Future<dynamic> getHospitals() => _get('/api/v1/hospitals');
  
  static Future<dynamic> getHospitalIncoming(String hospitalId) => _get('/api/v1/hospitals/$hospitalId/incoming');
  
  static Future<dynamic> getEvents() => _get('/api/v1/events');
  
  static Future<dynamic> getEvidence() => _get('/api/v1/evidence');
  
  static Future<dynamic> geocode(String query) => _get('/api/v1/geocode?q=${Uri.encodeComponent(query)}');
  
  static Future<dynamic> requestRoute(Map<String, dynamic> data) => _post('/api/v1/route', data);

  static Future<void> registerDeviceToken(String userId, String token) async {
    await _post('/api/v1/devices/register', {
      'user_id': userId,
      'device_token': token,
      'platform': 'android',
    });
  }

  static Future<void> updateDeviceLocation({
    required String userId,
    required String deviceToken,
    required String idToken,
    required double lat,
    required double lon,
    double? accuracyM,
  }) async {
    try {
      final response = await http
          .post(
            Uri.parse('${ApiConfig.baseUrl}/api/v1/devices/location'),
            headers: {
              'Content-Type': 'application/json',
              'Authorization': 'Bearer $idToken',
            },
            body: jsonEncode({
              'user_id': userId,
              'device_token': deviceToken,
              'lat': lat,
              'lon': lon,
              if (accuracyM != null) 'accuracy_m': accuracyM,
            }),
          )
          .timeout(const Duration(seconds: _timeoutSeconds));

      _handleResponse(response);
    } catch (e) {
      _handleError(e);
    }
  }

  static Future<dynamic> deleteEvidenceForReport({
    required String reportId,
    required String idToken,
  }) async {
    try {
      final response = await http
          .delete(
            Uri.parse(
              '${ApiConfig.baseUrl}/api/v1/admin/evidence/by-request/${Uri.encodeComponent(reportId)}',
            ),
            headers: {
              'Authorization': 'Bearer $idToken',
            },
          )
          .timeout(const Duration(seconds: _timeoutSeconds));

      return _handleResponse(response);
    } catch (e) {
      _handleError(e);
    }
  }

  static Future<dynamic> deleteEvidenceById({
    required String evidenceId,
    required String idToken,
  }) async {
    try {
      final response = await http
          .delete(
            Uri.parse(
              '${ApiConfig.baseUrl}/api/v1/admin/evidence/${Uri.encodeComponent(evidenceId)}',
            ),
            headers: {
              'Authorization': 'Bearer $idToken',
            },
          )
          .timeout(const Duration(seconds: _timeoutSeconds));

      return _handleResponse(response);
    } catch (e) {
      _handleError(e);
    }
  }

  static Future<void> uploadEvidence({
    required File file,
    String? userId,
    String? requestId,
    String? vehicleId,
    String? junctionId,
    String? description,
    String type = 'PHOTO',
    String source = 'APP',
  }) async {
    try {
      var request = http.MultipartRequest('POST', Uri.parse('${ApiConfig.baseUrl}/api/v1/evidence'));
      request.files.add(await http.MultipartFile.fromPath('file', file.path));

      // Use backend expected field names. Pass only if non-null and not empty.
      if (userId != null && userId.isNotEmpty) request.fields['user_id'] = userId;
      if (requestId != null && requestId.isNotEmpty) request.fields['request_id'] = requestId;
      if (vehicleId != null && vehicleId.isNotEmpty) request.fields['vehicle_id'] = vehicleId;
      if (junctionId != null && junctionId.isNotEmpty) request.fields['junction_id'] = junctionId;
      if (description != null && description.isNotEmpty) request.fields['description'] = description;
      if (type.isNotEmpty) request.fields['type'] = type;
      if (source.isNotEmpty) request.fields['source'] = source;

      var response = await request.send().timeout(const Duration(seconds: 15));
      if (response.statusCode >= 400) {
        String errorMessage = 'Evidence upload failed';
        try {
          final responseBody = await response.stream.bytesToString();
          final decoded = jsonDecode(responseBody);
          if (decoded is Map && decoded.containsKey('message')) {
            errorMessage = decoded['message'];
          }
        } catch (_) {}
        throw PrioWayApiException(errorMessage, response.statusCode);
      }
    } catch (e) {
      _handleError(e);
    }
  }
}