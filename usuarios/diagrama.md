erDiagram
    %% MÓDULO SECURITY
    User {
        int id PK
        string username
        string email
        string first_name
        string last_name
        string password
        datetime date_joined
    }
    
    Profile {
        int id PK
        int user_id FK
        string bio
        string phone
        string address
        datetime created_at
        boolean is_active
    }
    
    Role {
        int id PK
        string name
        string description
        datetime created_at
    }
    
    %% MÓDULO CORE  
    Project {
        int id PK
        string name
        text description
        string area
        string status
        int created_by FK
        datetime created_at
        datetime updated_at
        int max_collaborators
        boolean is_public
    }
    
    ProjectMembership {
        int id PK
        int user_id FK
        int project_id FK
        string role
        string status
        datetime joined_at
        int invited_by FK
    }
    
    ProjectInvitation {
        int id PK
        int project_id FK
        string email
        string role
        string status
        uuid token
        int invited_by FK
        datetime created_at
        datetime expires_at
    }
    
    ProjectRequest {
        int id PK
        int user_id FK
        int project_id FK
        text message
        string status
        datetime created_at
        datetime reviewed_at
        int reviewed_by FK
    }
    
    %% MÓDULO ARTICULOS
    BibFile {
        int id PK
        int project_id FK
        string file
        string original_filename
        int uploaded_by FK
        datetime uploaded_at
        boolean processed
        int articles_count
    }
    
    Article {
        int id PK
        int project_id FK
        int bib_file_id FK
        int assigned_to FK
        string bib_key
        text title
        text authors
        string journal
        string year
        string volume
        string number
        string pages
        string publisher
        string doi
        string url
        text abstract
        text keywords
        string status
        datetime created_at
        datetime assigned_at
        datetime completed_at
    }
    
    ArticleAnalysis {
        int id PK
        int article_id FK
        int analyzed_by FK
        float r_squared
        int sample_size
        float effect_size
        float p_value
        float confidence_interval_lower
        float confidence_interval_upper
        string study_design
        text methodology
        text variables_studied
        string statistical_method
        int quality_score
        text bias_assessment
        text limitations
        datetime created_at
        datetime updated_at
        boolean is_final
    }
    
    ArticleComment {
        int id PK
        int article_id FK
        int user_id FK
        text comment
        datetime created_at
    }
    
    ArticleWorkLog {
        int id PK
        int article_id FK
        int user_id FK
        string action
        text description
        datetime timestamp
    }
    
    %% RELACIONES
    User ||--|| Profile : has
    User ||--o{ ProjectMembership : participates
    User ||--o{ Project : creates
    User ||--o{ ProjectInvitation : sends
    User ||--o{ ProjectRequest : makes
    User ||--o{ BibFile : uploads
    User ||--o{ Article : assigned_to
    User ||--o{ ArticleAnalysis : analyzes
    User ||--o{ ArticleComment : writes
    User ||--o{ ArticleWorkLog : logs
    
    Project ||--o{ ProjectMembership : has
    Project ||--o{ ProjectInvitation : receives
    Project ||--o{ ProjectRequest : receives
    Project ||--o{ BibFile : contains
    Project ||--o{ Article : contains
    
    BibFile ||--o{ Article : generates
    
    Article ||--|| ArticleAnalysis : has
    Article ||--o{ ArticleComment : receives
    Article ||--o{ ArticleWorkLog : tracks