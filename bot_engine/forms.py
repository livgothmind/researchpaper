from django import forms
from .models import ResearchPoster


class PosterUploadForm(forms.ModelForm):
    notes = forms.CharField(
        max_length=500,
        widget=forms.Textarea(attrs={
            'rows': 3,
            'placeholder': 'Optional: personal notes about this paper…',
            'class': 'form-control',
            'maxlength': '500',
        }),
        required=False,
        label='Notes',
    )
    tags = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={
            'placeholder': 'e.g. brain tumor, segmentation, 3D reconstruction…',
            'class': 'form-control',
            'maxlength': '200',
        }),
        required=False,
        label='Tags',
        help_text='Comma-separated — AI will match them to database categories',
    )

    class Meta:
        model = ResearchPoster
        fields = ['image', 'notes', 'tags']

    ALLOWED_MIME_TYPES = [
        'image/jpeg', 'image/png', 'image/gif',
        'image/webp', 'image/bmp', 'image/tiff',
    ]
    MAX_UPLOAD_SIZE = 20 * 1024 * 1024  # 20 MB — matches upload.js

    def clean_image(self):
        image = self.cleaned_data.get('image')
        if not image:
            return image
        if image.size > self.MAX_UPLOAD_SIZE:
            raise forms.ValidationError("File troppo grande (massimo 20 MB).")
        mime = getattr(image, 'content_type', '')
        if mime not in self.ALLOWED_MIME_TYPES:
            raise forms.ValidationError(
                "Tipo di file non valido. Formati ammessi: JPG, PNG, GIF, WEBP, BMP, TIFF."
            )
        return image


class SubfieldsMultipleWidget(forms.CheckboxSelectMultiple):
    """Checkbox widget that groups subfields by macro-category."""
    template_name = 'widgets/subfields_grouped.html'

    def __init__(self, grouped_choices=None, *args, **kwargs):
        self.grouped_choices = grouped_choices or ResearchPoster.SUBFIELDS_GROUPED
        flat = []
        for _, _, items in self.grouped_choices:
            flat.extend(items)
        super().__init__(*args, choices=flat, **kwargs)

    def get_context(self, name, value, attrs):
        ctx = super().get_context(name, value, attrs)
        ctx['widget']['grouped_choices'] = self.grouped_choices
        ctx['widget']['selected_values'] = value or []
        return ctx


class PosterEditForm(forms.ModelForm):
    subfields = forms.MultipleChoiceField(
        choices=ResearchPoster.SUBFIELD_CHOICES,
        widget=SubfieldsMultipleWidget(),
        required=False,
        label='Subfields',
    )

    class Meta:
        model = ResearchPoster
        fields = ['title', 'authors', 'paper_link', 'github_link', 'summary', 'category', 'subfields', 'tags', 'validation_status', 'notes']
        widgets = {
            'summary': forms.Textarea(attrs={'rows': 4}),
            'notes': forms.Textarea(attrs={'rows': 4, 'maxlength': '500'}),
            'tags': forms.TextInput(attrs={'maxlength': '200'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.initial['subfields'] = self.instance.subfields_list

    def clean_subfields(self):
        """Convert list of selected subfields back to comma-separated string."""
        return ','.join(self.cleaned_data.get('subfields', []))

    def save(self, commit=True):
        poster = super().save(commit=False)
        poster.subfields = self.cleaned_data.get('subfields', '')
        poster.derive_category_from_subfields()
        if commit:
            poster.save()
        return poster