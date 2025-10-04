[app]
# (str) Title of your application
title = Мониторинг сервера HA

# (str) Package name
package.name = hamonitor

# (str) Package domain (reverse domain)
package.domain = org.example

# (str) Source code where the main.py is located
source.dir = .

# (list) Source files to include (let buildozer find them automatically if omitted)
source.include_exts = py,png,jpg,json,kv,ini

# (str) Application versioning
version = 0.1

# (list) Application requirements
# kivy, garden graph and requests are required
requirements = python3,kivy==2.1.0,kivy_garden.graph,requests,pillow

# (str) Icon of the application
icon.filename = icons/app_icon.png

# (str) Supported orientation
orientation = portrait

# (list) Android permissions
android.permissions = INTERNET

# (bool) If you change it to True, it will attempt to use an SDK/NDK installed on the host
# Build in docker image used by workflow, so leave defaults
# (other defaults omitted for brevity)
