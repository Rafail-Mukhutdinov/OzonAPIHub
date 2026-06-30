import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import 'package:provider/provider.dart';
import '../providers/auth_provider.dart';
import '../services/api.dart';

class AdminUsersScreen extends StatefulWidget {
  const AdminUsersScreen({super.key});

  @override
  State<AdminUsersScreen> createState() => _AdminUsersScreenState();
}

class _AdminUsersScreenState extends State<AdminUsersScreen> {
  late final OzonApiClient api;
  List<Map<String, dynamic>> users = [];
  bool loading = true;
  String? error;

  @override
  void initState() {
    super.initState();
    final auth = Provider.of<AuthProvider>(context, listen: false);
    api = OzonApiClient(authProvider: auth);
    _loadUsers();
  }

  Future<void> _loadUsers() async {
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final response = await api.dio.get('/auth/admin/users');
      setState(() {
        users = (response.data as List).cast<Map<String, dynamic>>();
        loading = false;
      });
    } catch (e) {
      setState(() {
        error = "Не удалось загрузить список пользователей. Проверьте права администратора.";
        loading = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Управление пользователями'),
        actions: [
          IconButton(
            icon: const Icon(Icons.refresh),
            onPressed: _loadUsers,
          ),
        ],
      ),
      body: loading
          ? const Center(child: CircularProgressIndicator())
          : error != null
              ? Center(child: Text(error!, textAlign: TextAlign.center))
              : ListView.builder(
                  itemCount: users.length,
                  itemBuilder: (context, index) {
                    final user = users[index];
                    final String email = user['email'] ?? 'No email';
                    final bool isActive = user['is_active'] ?? false;
                    final bool hasCreds = user['has_credentials'] ?? false;
                    final bool isAdmin = user['is_admin'] ?? false;

                    return Card(
                      margin: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                      child: ListTile(
                        leading: CircleAvatar(
                          backgroundColor: isAdmin ? Colors.amber : Colors.blue,
                          child: Icon(
                            isAdmin ? Icons.admin_panel_settings : Icons.person,
                            color: Colors.white,
                          ),
                        ),
                        title: Text(email),
                        subtitle: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text('Status: ${isActive ? "Active" : "Inactive"}'),
                            Text('Ozon Keys: ${hasCreds ? "Connected ✅" : "Not connected ❌"}'),
                          ],
                        ),
                        trailing: isAdmin 
                          ? const Chip(label: Text('ADMIN'), backgroundColor: Colors.amber)
                          : null,
                      ),
                    );
                  },
                ),
    );
  }
}
