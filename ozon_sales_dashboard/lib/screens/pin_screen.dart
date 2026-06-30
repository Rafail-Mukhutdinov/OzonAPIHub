import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../providers/auth_provider.dart';

class PinScreen extends StatefulWidget {
  final VoidCallback onAuthenticated;

  const PinScreen({super.key, required this.onAuthenticated});

  @override
  State<PinScreen> createState() => _PinScreenState();
}

class _PinScreenState extends State<PinScreen> {
  String _enteredPin = "";
  String? _error;

  void _onDigitPress(String digit) {
    if (_enteredPin.length < 4) {
      setState(() {
        _enteredPin += digit;
        _error = null;
      });

      if (_enteredPin.length == 4) {
        _verifyPin();
      }
    }
  }

  void _onBackspace() {
    if (_enteredPin.isNotEmpty) {
      setState(() {
        _enteredPin = _enteredPin.substring(0, _enteredPin.length - 1);
      });
    }
  }

  void _verifyPin() {
    final auth = Provider.of<AuthProvider>(context, listen: false);
    if (auth.verifyPin(_enteredPin)) {
      widget.onAuthenticated();
    } else {
      setState(() {
        _enteredPin = "";
        _error = "Неверный ПИН-код";
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.lock_outline, size: 64, color: Colors.blue),
            const SizedBox(height: 24),
            const Text(
              "Введите ПИН-код",
              style: TextStyle(fontSize: 24, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 16),
            
            // Индикаторы ввода
            Row(
              mainAxisAlignment: MainAxisAlignment.center,
              children: List.generate(4, (index) {
                return Container(
                  margin: const EdgeInsets.symmetric(horizontal: 8),
                  width: 20,
                  height: 20,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: index < _enteredPin.length 
                        ? Colors.blue 
                        : Colors.grey.shade300,
                  ),
                );
              }),
            ),
            
            if (_error != null) ...[
              const SizedBox(height: 16),
              Text(_error!, style: const TextStyle(color: Colors.red)),
            ],

            const SizedBox(height: 48),

            // Цифровая клавиатура
            Expanded(
              child: GridView.count(
                crossAxisCount: 3,
                padding: const EdgeInsets.symmetric(horizontal: 48),
                children: [
                  ...["1", "2", "3", "4", "5", "6", "7", "8", "9"].map((d) => _buildKey(d)),
                  _buildBiometricKey(),
                  _buildKey("0"),
                  _buildBackspaceKey(),
                ],
              ),
            ),
            
            TextButton(
              onPressed: () => Provider.of<AuthProvider>(context, listen: false).clearAllData(),
              child: const Text("Войти с другим аккаунтом"),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildKey(String digit) {
    return IconButton(
      onPressed: () => _onDigitPress(digit),
      icon: Text(digit, style: const TextStyle(fontSize: 28)),
    );
  }

  Widget _buildBackspaceKey() {
    return IconButton(
      onPressed: _onBackspace,
      icon: const Icon(Icons.backspace_outlined),
    );
  }

  Widget _buildBiometricKey() {
    final auth = Provider.of<AuthProvider>(context, listen: false);
    if (!auth.biometricEnabled) return const SizedBox();
    
    return IconButton(
      onPressed: () async {
        if (await auth.authenticateWithBiometrics()) {
          widget.onAuthenticated();
        }
      },
      icon: const Icon(Icons.fingerprint, size: 32, color: Colors.blue),
    );
  }
}
