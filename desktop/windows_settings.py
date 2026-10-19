"""Native WinForms settings dialog; called on the owning UI thread."""
def show_settings(desktop):
    from System.Drawing import Point, Size
    from System.Windows.Forms import (Form, Label, TextBox, ComboBox, Button,
        FormBorderStyle, ComboBoxStyle, DialogResult, FormStartPosition)
    from desktop.windows_shell import message
    form = Form()
    form.Text, form.ClientSize = 'OpenShorts settings', Size(520,265)
    form.FormBorderStyle = FormBorderStyle.FixedDialog
    form.StartPosition = FormStartPosition.CenterParent
    form.MaximizeBox = form.MinimizeBox = False
    def label(text, y):
        item = Label()
        item.Text, item.Location, item.Size = text, Point(20,y), Size(480,20)
        form.Controls.Add(item)
    label('Gemini API key (protected by Windows)',15)
    key = TextBox()
    key.Location, key.Size = Point(20,40), Size(480,24)
    key.UseSystemPasswordChar = True
    try: key.Text = desktop.vault.load()
    except OSError: message('The saved key could not be decrypted. Enter it again.', error=True)
    form.Controls.Add(key)
    def combo(values, current, y):
        item = ComboBox()
        item.Location, item.Size = Point(20,y), Size(220,24)
        item.DropDownStyle = ComboBoxStyle.DropDownList
        for value in values: item.Items.Add(value)
        item.SelectedItem = current
        form.Controls.Add(item)
        return item
    label('FFmpeg encoder • automatic CPU fallback',75)
    encoder = combo(('auto','x264','nvenc'),desktop.storage.settings()['encoder'],98)
    label('Performance • one processing job at a time',132)
    preset = combo(('quiet','balanced','performance'),desktop.storage.settings()['preset'],155)
    label('Changes apply next launch. Other dashboard keys last for this session.',188)
    save = Button()
    save.Text, save.Location, save.Size = 'Save',Point(400,220),Size(100,28)
    save.DialogResult = DialogResult.OK
    form.Controls.Add(save)
    form.AcceptButton = save
    if form.ShowDialog(desktop.window.native) == DialogResult.OK:
        try:
            desktop.vault.save(str(key.Text).strip())
            desktop.storage.save_settings({'encoder':str(encoder.SelectedItem),'preset':str(preset.SelectedItem)})
        except (OSError,ValueError): message('Settings could not be saved. Check Windows profile permissions.',error=True)
    form.Dispose()
