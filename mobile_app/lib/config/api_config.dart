class ApiConfig {
  static const String baseUrl = String.fromEnvironment(
    'PRIOWAY_API_URL',
    defaultValue: 'http://192.168.137.1:5000',
  );
}